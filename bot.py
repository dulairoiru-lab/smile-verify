import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 特権インテントは不要(スラッシュコマンドとボタンのみ使用するため)
intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)  # プレフィックスコマンドは使わない
tree = bot.tree

CONFIG_PATH = "verify_config.json"


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


verify_config = load_config()  # { "guild_id(str)": role_id(int) }

TICKET_CONFIG_PATH = "ticket_config.json"


def load_ticket_config() -> dict:
    if os.path.exists(TICKET_CONFIG_PATH):
        try:
            with open(TICKET_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_ticket_config(data: dict) -> None:
    with open(TICKET_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


ticket_config = load_ticket_config()  # { "guild_id(str)": next_number(int) }


async def create_ticket_channel(interaction: discord.Interaction, ticket_type: str, product_name: str = None):
    guild = interaction.guild
    gid = str(guild.id)

    number = ticket_config.get(gid, 1)
    ticket_config[gid] = number + 1
    save_ticket_config(ticket_config)

    category = discord.utils.get(guild.categories, name="チケット")
    if category is None:
        try:
            category = await guild.create_category("チケット")
        except discord.Forbidden:
            category = None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    try:
        channel = await guild.create_text_channel(
            name=f"ticket-{number}",
            category=category,
            overwrites=overwrites,
            reason=f"{interaction.user} によるチケット作成",
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "Botにチャンネルを作成する権限がありません。サーバー設定でBotのロールに「チャンネルの管理」権限を付与してください。",
            ephemeral=True,
        )
        return

    embed = discord.Embed(color=discord.Color.blurple())
    embed.add_field(name="種類", value=ticket_type, inline=True)
    embed.add_field(name="作成者", value=interaction.user.mention, inline=True)
    if product_name:
        embed.add_field(name="商品名", value=product_name, inline=False)

    await channel.send(content="管理者の対応をお待ちください。", embed=embed)
    await interaction.response.send_message(f"チケットを作成しました: {channel.mention}", ephemeral=True)


class ProductNameModal(discord.ui.Modal, title="ご購入希望チケット"):
    product_name = discord.ui.TextInput(label="商品名", placeholder="ご希望の商品名を入力してください", max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        await create_ticket_channel(interaction, "ご購入をご希望な方", product_name=str(self.product_name))


class TicketPanelView(discord.ui.View):
    """チケットパネルのボタン。timeout=None にすることでBot再起動後も機能し続ける(persistent view)。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="対応が必要な場合", style=discord.ButtonStyle.secondary, custom_id="ticket_type_support")
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket_channel(interaction, "対応が必要な場合")

    @discord.ui.button(label="ご購入をご希望な方", style=discord.ButtonStyle.success, custom_id="ticket_type_purchase")
    async def purchase_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProductNameModal())


class VerifyView(discord.ui.View):
    """認証ボタン。timeout=None にすることでBot再起動後もボタンが機能し続ける(persistent view)。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="認証する", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        role_id = verify_config.get(guild_id)

        if role_id is None:
            await interaction.response.send_message(
                "認証用のロールが設定されていません。管理者に `/verify` の実行を依頼してください。",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message(
                "設定されたロールが見つかりません(削除された可能性があります)。管理者に確認してください。",
                ephemeral=True,
            )
            return

        member = interaction.user
        if role in member.roles:
            await interaction.response.send_message("既に認証済みです。", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason="認証ボタンによる自動付与")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Botにロールを付与する権限がありません。サーバー設定でBotのロールに「ロールの管理」権限を付与し、"
                "Botのロールを付与したいロールより上に配置してください。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(f"認証が完了しました。「{role.name}」ロールを付与しました。", ephemeral=True)


@bot.event
async def on_ready():
    # persistent viewとして登録(再起動後もボタンが機能し続けるようにする)
    bot.add_view(VerifyView())
    bot.add_view(TicketPanelView())

    # 各サーバーにスラッシュコマンドを即時反映(グローバル同期は反映まで時間がかかるため)
    for guild in bot.guilds:
        try:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        except discord.HTTPException:
            pass

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


@bot.event
async def on_guild_join(guild: discord.Guild):
    # Botが新しいサーバーに参加したときにスラッシュコマンドを即時反映する
    try:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    except discord.HTTPException:
        pass


@tree.command(name="verify", description="認証用のロールを設定し、認証メッセージを送信します")
@app_commands.describe(role="認証した人に付与するロール")
@app_commands.checks.has_permissions(administrator=True)
async def verify(interaction: discord.Interaction, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "Botよりロール順位が高いため設定できません。サーバー設定でBotのロール順位を上げてください。",
            ephemeral=True,
        )
        return

    verify_config[str(interaction.guild_id)] = role.id
    save_config(verify_config)

    embed = discord.Embed(
        title="サーバー認証",
        description="下の「認証する」ボタンを押すと、認証が完了しロールが付与されます。",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed, view=VerifyView())


@verify.error
async def verify_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを使う権限がありません(管理者権限が必要です)。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)
        raise error


@tree.command(name="ticket", description="チケットパネルを設置します")
@app_commands.checks.has_permissions(administrator=True)
async def ticket(interaction: discord.Interaction):
    embed = discord.Embed(
        title="チケット作成",
        description="ご用件に合わせて、下のボタンからチケットを作成してください。",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="対応が必要な場合", value="サポートが必要な場合はこちら", inline=False)
    embed.add_field(name="ご購入をご希望な方", value="商品のご購入を希望される方はこちら", inline=False)
    await interaction.response.send_message(embed=embed, view=TicketPanelView())


@ticket.error
async def ticket_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("このコマンドを使う権限がありません(管理者権限が必要です)。", ephemeral=True)
    else:
        await interaction.response.send_message(f"エラーが発生しました: {error}", ephemeral=True)
        raise error


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません。.envファイルを確認してください。")
    bot.run(TOKEN)
