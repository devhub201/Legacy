import os
from datetime import date
import discord
from discord.ext import commands, tasks
import database as db

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OWNER_ID = os.environ.get("OWNER_DISCORD_ID", "")
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
ACCENT_COLOR = discord.Color.from_rgb(255, 255, 255)


def build_credential_embed(vps: dict) -> discord.Embed:
    embed = discord.Embed(title="🎉 Your VPS is Ready!",
        description=f"Thanks for choosing **Legacy Cloud**! Your **{vps['plan']}** instance has been provisioned.",
        color=ACCENT_COLOR)
    embed.add_field(name="🌐 IP Address", value=f"```{vps['node_ip']}```", inline=True)
    embed.add_field(name="🔌 SSH Port", value=f"```{vps['ssh_port']}```", inline=True)
    embed.add_field(name="👤 Username", value=f"```{vps['ssh_username']}```", inline=True)
    embed.add_field(name="🔑 Password", value=f"```{vps['ssh_password']}```", inline=False)
    embed.add_field(name="📡 Connect via SSH", value=f"```ssh {vps['ssh_username']}@{vps['node_ip']} -p {vps['ssh_port']}```", inline=False)
    embed.add_field(name="💾 Specs", value=f"{vps['ram_limit']} RAM • {vps['cpu_limit']} • {vps['disk_limit']} Disk", inline=False)
    embed.set_footer(text="Legacy Cloud • Keep these credentials safe.")
    return embed


async def drain_delivery_queue():
    for item in db.get_pending_deliveries():
        vps = db.get_vps(item["vps_id"])
        if not vps:
            db.mark_delivered(item["id"], status="failed"); continue
        try:
            user = await bot.fetch_user(int(vps["discord_id"]))
            await user.send(embed=build_credential_embed(vps))
            db.mark_delivered(item["id"], status="sent")
        except Exception as e:
            print(f"Delivery failed for vps {vps['id']}: {e}")
            db.mark_delivered(item["id"], status="failed")


@tasks.loop(seconds=8)
async def delivery_queue_loop():
    await drain_delivery_queue()


def build_violation_embed(vps: dict, reason: str) -> discord.Embed:
    embed = discord.Embed(
        title="💀 CAUGHT RED-HANDED — MINING DETECTED",
        description=(
            f"Bhai seriously? `{reason}` chalate hue pakde gaye, on a **Legacy Cloud VPS**, "
            f"jaise humein pata hi nahi chalega. 👽\n\n"
            f"**{vps['plan']}** — ab suspended hai. Instant. No warning shots, no drama, "
            f"seedha unplugged. 🔌\n\n"
            "Yeh koi small hosting nahi hai jaha aisi harkatein chal jaati hain — humara system "
            "24/7 dekh raha tha, tumhe pata bhi nahi chala kab pakde gaye.\n\n"
            "Agar lagta hai galti se hua ya baat karni hai, ticket khol do. Warna doosri baar "
            "pakde gaye toh account hi gayab ho jayega, refund bhi nahi milega. 🚪"
        ),
        color=discord.Color.red(),
    )
    embed.set_footer(text="Legacy Cloud • Nice try though 💀")
    return embed


async def drain_violation_queue():
    for item in db.get_pending_violations():
        vps = db.get_vps(item["vps_id"])
        if not vps:
            db.mark_violation_sent(item["id"]); continue
        try:
            user = await bot.fetch_user(int(vps["discord_id"]))
            await user.send(embed=build_violation_embed(vps, item["reason"]))
        except Exception as e:
            print(f"Violation notice failed for vps {vps['id']}: {e}")
        db.mark_violation_sent(item["id"])
        if OWNER_ID:
            owner = await bot.fetch_user(int(OWNER_ID))
            await owner.send(f"🚫 **Auto-suspended** VPS `{vps['container_name']}` (<@{vps['discord_id']}>) — mining detected: `{item['reason']}`")


@tasks.loop(seconds=10)
async def violation_queue_loop():
    await drain_violation_queue()


class RenewalReasonModal(discord.ui.Modal, title="We're sorry to see you go"):
    rating = discord.ui.TextInput(label="Rate our service (1-5)", max_length=1, required=True)
    reason = discord.ui.TextInput(label="Why are you stopping our service?", style=discord.TextStyle.paragraph, required=True, max_length=500)

    def __init__(self, vps_id, customer_name, plan):
        super().__init__()
        self.vps_id, self.customer_name, self.plan = vps_id, customer_name, plan

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rating_val = int(str(self.rating.value)); assert 1 <= rating_val <= 5
        except Exception:
            await interaction.response.send_message("Rating must be 1-5.", ephemeral=True); return
        db.set_vps_status(self.vps_id, "cancelled", rating_val, str(self.reason.value))
        await interaction.response.send_message("Thanks for your feedback. 🙏", ephemeral=True)
        if OWNER_ID:
            owner = await bot.fetch_user(int(OWNER_ID))
            embed = discord.Embed(title="❌ Renewal Declined", color=discord.Color.red())
            embed.add_field(name="Customer", value=self.customer_name, inline=True)
            embed.add_field(name="Plan", value=self.plan, inline=True)
            embed.add_field(name="Rating", value=f"{rating_val}/5 ⭐", inline=True)
            embed.add_field(name="Reason", value=str(self.reason.value), inline=False)
            await owner.send(embed=embed)


class RenewalDecisionView(discord.ui.View):
    def __init__(self, vps_id, customer_name, plan):
        super().__init__(timeout=None)
        self.vps_id, self.customer_name, self.plan = vps_id, customer_name, plan

    @discord.ui.button(label="Yes, continue", style=discord.ButtonStyle.green, emoji="✅")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        db.set_vps_status(self.vps_id, "renewed")
        await interaction.response.edit_message(content=None, embed=discord.Embed(
            title="✅ Renewal Confirmed", description="Thank you for staying with Legacy Cloud!", color=discord.Color.green()), view=None)
        if OWNER_ID:
            owner = await bot.fetch_user(int(OWNER_ID))
            await owner.send(f"✅ **{self.customer_name}** confirmed renewal for **{self.plan}**")

    @discord.ui.button(label="No, stop it", style=discord.ButtonStyle.red, emoji="❌")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RenewalReasonModal(self.vps_id, self.customer_name, self.plan))


@tasks.loop(hours=24)
async def renewal_check_loop():
    today_str = date.today().isoformat()
    due = db.get_due_renewals(today_str)
    owner = await bot.fetch_user(int(OWNER_ID)) if OWNER_ID else None
    for vps in due:
        try:
            customer = await bot.fetch_user(int(vps["discord_id"]))
        except Exception:
            continue
        if owner:
            await owner.send(f"⏰ **{customer.name}**'s plan (**{vps['plan']}**) renews today.")
        try:
            embed = discord.Embed(title="🔔 Subscription Renewal",
                description=f"Hey {customer.name}! Your plan **{vps['plan']}** renews today.\n\nContinue this service?", color=ACCENT_COLOR)
            await customer.send(embed=embed, view=RenewalDecisionView(vps["id"], customer.name, vps["plan"]))
        except discord.Forbidden:
            if owner:
                await owner.send(f"⚠️ Couldn't DM {customer.name} — VPS #{vps['id']}")


@tasks.loop(seconds=15)
async def heartbeat_loop():
    db.update_heartbeat()


@renewal_check_loop.before_loop
@delivery_queue_loop.before_loop
@heartbeat_loop.before_loop
@violation_queue_loop.before_loop
async def before_loops():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Legacy Bot online as {bot.user}")
    delivery_queue_loop.start(); renewal_check_loop.start(); heartbeat_loop.start(); violation_queue_loop.start()


if __name__ == "__main__":
    bot.run(TOKEN)
