"""OrangeOrangus Discord bot: OranguTeam join role, moderation and server /setup.
Run: DISCORD_TOKEN=... python discord_bot/bot.py"""
import datetime, json, os, random, re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

import filters

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
OG_FILE = Path(__file__).parent / "og_members.json"
VERSION = "2026-10-31b"
RAID_FILE = Path(__file__).parent / "raid_points.json"
OG_ROLE_FILE = Path(__file__).parent / "og_role.json"
COUNTER_PREFIX = CFG["member_counter"].split("{")[0]
tracker = filters.Tracker(CFG["spam_messages"], CFG["spam_seconds"], CFG["duplicate_limit"])


def norm(name):
    """Name without emoji, symbols and case: "🛡️ Mod" -> "mod", "💬-general-chat" -> "generalchat"."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find(items, name):
    """Finds a role/channel by its config name, also after it was renamed with emoji or symbols."""
    return discord.utils.get(items, name=name) or next((i for i in items if norm(i.name) == norm(name)), None)


def find_role(guild, name):
    return og_role(guild) if norm(name) == norm(CFG["og_role"]) else find(guild.roles, name)


def is_staff(member):
    return member.guild_permissions.manage_messages or any(norm(r.name) in {norm(n) for n in CFG["staff_roles"]} for r in member.roles)


async def log(guild, text):
    channel = find(guild.text_channels, CFG["log_channel"])
    if channel:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_ready():
    print(f"Connected as {client.user}")
    if not refresh_counters.is_running():
        refresh_counters.start()
    if not client.guilds:
        print("⚠️ The bot is not in any server: invite it with the OAuth2 link (scopes bot + applications.commands).")
    # Per-server sync so /setup shows up immediately.
    for guild in client.guilds:
        try:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"✅ /setup ready in server {guild.name} (or type !setup)")
            given = await grant_og(guild)
            if given:
                print(f"🏅 OG given to {given} members in {guild.name}")
        except discord.HTTPException as e:
            print(f"⚠️ {guild.name}: /setup not registered ({e}). Re-invite the bot with the applications.commands scope, "
                  "or type !setup in the server.")


def og_role(guild):
    """The OG role. Remembered by id, so renaming it in Discord does not break anything."""
    saved = json.loads(OG_ROLE_FILE.read_text()).get(str(guild.id)) if OG_ROLE_FILE.exists() else None
    role = guild.get_role(saved) if saved else None
    if not role:
        # Match ignoring case, emoji and symbols: "OG", "og", "🔥 OG", "OG 🦧" all count.
        want = re.sub(r"[^a-z0-9]", "", CFG["og_role"].lower())
        role = next((r for r in guild.roles if re.sub(r"[^a-z0-9]", "", r.name.lower()) == want), None)
    if not role and OG_FILE.exists():
        # Renamed before the id was saved: it is the role held by exactly the members who got OG.
        granted = set(json.loads(OG_FILE.read_text()))
        holders = {m.id for m in guild.members if m.id in granted}
        others = {r["name"] for r in CFG["roles"]} - {CFG["og_role"]}
        role = next((r for r in guild.roles if holders and not r.managed and r != guild.default_role
                     and r.name not in others and {m.id for m in r.members} == holders), None)
    if role and role.id != saved:
        data = json.loads(OG_ROLE_FILE.read_text()) if OG_ROLE_FILE.exists() else {}
        data[str(guild.id)] = role.id
        OG_ROLE_FILE.write_text(json.dumps(data))
    return role


async def grant_og(guild):
    """Gives OG to the first og_limit members by join date. Saved to og_members.json so it survives restarts."""
    role = og_role(guild)
    if not role:
        spec = next(r for r in CFG["roles"] if r["name"] == CFG["og_role"])
        try:
            role = await guild.create_role(name=spec["name"], colour=discord.Colour.from_str(spec["color"]),
                                           permissions=perms(spec["permissions"]), hoist=True, reason="OG role was missing")
            await log(guild, "ℹ️ OG role was missing, so the bot created it again.")
        except discord.HTTPException as e:
            print(f"⚠️ Could not create OG role: {e}")
            return 0
    granted = set(json.loads(OG_FILE.read_text())) if OG_FILE.exists() else set()
    granted |= {m.id for m in role.members}
    humans = sorted((m for m in guild.members if not m.bot), key=lambda m: m.joined_at or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
    picks = filters.og_picks(granted, [m.id for m in humans], CFG["og_limit"])
    # Members who already earned OG, left and came back get it back (their slot is theirs).
    picks += [m.id for m in humans if m.id in granted and role not in m.roles]
    given = 0
    for member_id in picks:
        try:
            await guild.get_member(member_id).add_roles(role, reason=f"First {CFG['og_limit']} members")
        except discord.HTTPException as e:
            print(f"⚠️ Could not give OG ({e}): move the bot role above OG.")
            await log(guild, f"⚠️ Could not give OG ({e.text or e}): in Server Settings → Roles drag the bot role above OG.")
            break
        granted.add(member_id)
        given += 1
    OG_FILE.write_text(json.dumps(sorted(granted)))
    return given


def humans(guild):
    return sum(not m.bot for m in guild.members)


def counter_channel(guild):
    return next((c for c in guild.voice_channels if c.name.startswith(COUNTER_PREFIX)), None)


renames = {}


async def update_counter(guild):
    """Renames the counter channel. Discord allows 2 renames per 10 minutes per channel:
    when the limit is reached the 1-minute loop below applies the latest total as soon as it can."""
    channel = counter_channel(guild)
    name = CFG["member_counter"].format(count=humans(guild))
    if not channel:
        # Created automatically at the top of INFO: nobody can join it, it only shows the number.
        info = find(guild.categories, CFG["categories"][0]["name"])
        try:
            await guild.create_voice_channel(name, category=info, position=0, reason="Member counter",
                                             overwrites={guild.default_role: discord.PermissionOverwrite(connect=False)})
            print(f"🦧 Member counter created in {guild.name}")
        except discord.HTTPException as e:
            print(f"⚠️ Counter not created: {e}")
        return
    if channel.name == name:
        return
    now = datetime.datetime.now().timestamp()
    recent = [t for t in renames.get(guild.id, []) if now - t < 600]
    if len(recent) >= 2:
        return
    try:
        await channel.edit(name=name, reason="Member counter")
        renames[guild.id] = recent + [now]
    except discord.HTTPException as e:
        print(f"⚠️ Counter not updated: {e}")


@tasks.loop(minutes=1)
async def refresh_counters():
    for guild in client.guilds:
        await update_counter(guild)


@client.event
async def on_member_remove(member):
    await update_counter(member.guild)


def og_report(guild):
    """Admin check of everything OG needs, in plain words."""
    role = og_role(guild)
    me = guild.me
    granted = json.loads(OG_FILE.read_text()) if OG_FILE.exists() else []
    lines = [f"🔎 **OG check** (bot version {VERSION})"]
    lines.append(f"{'✅' if role else '❌'} OG role {'found: ' + role.name if role else 'missing: run !setup'}")
    lines.append(f"{'✅' if me.guild_permissions.manage_roles else '❌'} bot can manage roles")
    if role:
        ok = me.top_role > role
        lines.append(f"{'✅' if ok else '❌'} bot role ({me.top_role.name}) is {'above' if ok else 'BELOW'} OG"
                     + ("" if ok else ": drag the bot role above OG in Server Settings → Roles"))
        lines.append(f"ℹ️ members with OG now: {len(role.members)}")
    lines.append(f"ℹ️ OG slots used: {len(granted)}/{CFG['og_limit']}")
    lines.append(f"{'✅' if client.intents.members else '❌'} members intent, {len(guild.members)} members visible")
    return "\n".join(lines)


@client.event
async def on_member_join(member):
    try:
        await _on_member_join(member)
    except Exception as e:
        # Never fail silently: the reason shows up in #mod-log.
        await log(member.guild, f"⚠️ Join handling failed for {member}: {type(e).__name__}: {e}")
        raise


async def _on_member_join(member):
    if not member.bot:
        await grant_og(member.guild)
    role = find_role(member.guild, CFG["join_role"])
    if role:
        await member.add_roles(role, reason="Automatic join role")
    else:
        await log(member.guild, f"⚠️ Role {CFG['join_role']} not found: run /setup")
    await update_counter(member.guild)
    welcome = find(member.guild.text_channels, "welcome")
    if welcome and not member.bot:
        text = CFG["welcome_message"].format(member=member.mention, count=humans(member.guild))
        await welcome.send(link_mentions(member.guild, text), allowed_mentions=discord.AllowedMentions(users=True))


@client.event
async def on_message(message):
    if message.guild and message.content.strip() == "!ogcheck" and message.author.guild_permissions.administrator:
        await message.channel.send(og_report(message.guild))
        return
    if message.guild and message.content.strip() == "!setup" and message.author.guild_permissions.administrator:
        await message.channel.send("⏳ Setup in progress...")
        done = await run_setup(message.guild)
        await message.channel.send("✅ Setup complete: " + (", ".join(done) or "everything was already in place"))
        return
    # Typed as plain text (not picked from the / menu) the link commands still answer.
    word = message.content.strip().lower()
    if message.guild and not message.author.bot and word[:1] in "/!" and word[1:] in CFG["link_commands"]:
        await message.channel.send(await link_text(message.guild, word[1:]))
        return
    if message.author.bot or not message.guild or is_staff(message.author):
        return
    category = message.channel.category.name if getattr(message.channel, "category", None) else ""
    result = filters.check(message.content, len(message.mentions) + len(message.role_mentions),
                           category == CFG["no_link_category"], CFG)
    if not result:
        burst = tracker.add(message.author.id, message.content)
        result = (burst, True) if burst else None
    if not result:
        return
    reason, timeout = result
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    action = "message deleted"
    if timeout:
        try:
            await message.author.timeout(datetime.timedelta(minutes=CFG["timeout_minutes"]), reason=reason)
            action += f" + timeout {CFG['timeout_minutes']} min"
        except discord.HTTPException:
            action += " (timeout failed: check the bot's permissions)"
    await message.channel.send(f"🦧 {message.author.mention}, {reason}. Please read #rules.", delete_after=10)
    await log(message.guild, f"🛡️ {message.author} in #{message.channel}: {reason} → {action}\n> {message.content[:300]}")


def link_mentions(guild, text):
    """Turns #channel-name and @Role into real Discord mentions."""
    def channel(m):
        ch = find(guild.text_channels, m.group(1))
        return ch.mention if ch else m.group(0)

    def role(m):
        r = find_role(guild, m.group(1))
        return r.mention if r else m.group(0)

    text = re.sub(r"#([a-z0-9-]+)", channel, text)
    return re.sub(r"@([A-Za-z]+)", role, text)


async def server_invite(guild):
    """Reuses the bot's permanent invite, or creates one on #welcome."""
    for invite in await guild.invites():
        if invite.inviter == guild.me and not invite.max_age:
            return invite.url
    channel = find(guild.text_channels, "welcome") or guild.text_channels[0]
    return (await channel.create_invite(max_age=0, max_uses=0, reason="/ds")).url


async def link_text(guild, name):
    text = CFG["link_commands"][name]["text"]
    return text.format(invite=await server_invite(guild)) if "{invite}" in text else text


def make_link_command(name, spec):
    async def callback(interaction: discord.Interaction):
        await interaction.response.send_message(await link_text(interaction.guild, name))
    app_commands.guild_only()(tree.command(name=name, description=spec["description"])(callback))


for _name, _spec in CFG["link_commands"].items():
    make_link_command(_name, _spec)


def perms(names):
    return discord.Permissions(**{n: True for n in names})


RAID = CFG["raid"]
X_POST = re.compile(r"^https://(www\.)?(x|twitter)\.com/\w+/status/\d+")


def raid_data():
    return json.loads(RAID_FILE.read_text()) if RAID_FILE.exists() else {"raids": [], "points": {}, "done": []}


@tree.command(name="raid", description="Staff: post an X link for a community raid")
@app_commands.describe(link="Link to the post on X", note="Optional extra line")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def raid(interaction: discord.Interaction, link: str, note: str = ""):
    if not is_staff(interaction.user):
        await interaction.response.send_message("⛔ Staff only.", ephemeral=True)
        return
    if not X_POST.match(link.strip()):
        await interaction.response.send_message("⚠️ Use a post link like https://x.com/orangeorangus/status/123", ephemeral=True)
        return
    channel = find(interaction.guild.text_channels, RAID["channel"])
    if not channel:
        await interaction.response.send_message("⚠️ #raids not found: run !setup", ephemeral=True)
        return
    role = find_role(interaction.guild, RAID["role"])
    ideas = "\n".join(f"• {r}" for r in random.sample(RAID["replies"], min(3, len(RAID["replies"]))))
    text = (f"🚨 **RAID TIME!** {role.mention if role else ''}\n{link.strip()}\n"
            + (f"{note}\n" if note else "")
            + f"\n1️⃣ Like ❤️  2️⃣ Repost 🔁  3️⃣ Reply in your own words. Ideas:\n{ideas}\n\n"
            f"Done? React {RAID['emoji']} to earn a raid point! 🦧")
    msg = await channel.send(text, allowed_mentions=discord.AllowedMentions(roles=True))
    await msg.add_reaction(RAID["emoji"])
    data = raid_data()
    data["raids"].append(msg.id)
    RAID_FILE.write_text(json.dumps(data))
    await interaction.response.send_message(f"✅ Raid posted in {channel.mention}", ephemeral=True)


@tree.command(name="raider", description="Get or remove the Raiders role (ping for every raid)")
@app_commands.guild_only()
async def raider(interaction: discord.Interaction):
    role = find_role(interaction.guild, RAID["role"])
    if not role:
        await interaction.response.send_message("⚠️ Raiders role not found yet.", ephemeral=True)
    elif role in interaction.user.roles:
        await interaction.user.remove_roles(role, reason="/raider")
        await interaction.response.send_message("🔕 Raiders role removed.", ephemeral=True)
    else:
        await interaction.user.add_roles(role, reason="/raider")
        await interaction.response.send_message("🔔 You're a Raider now! You'll be pinged for every raid. 🦧", ephemeral=True)


@tree.command(name="raidboard", description="Top raiders leaderboard")
@app_commands.guild_only()
async def raidboard(interaction: discord.Interaction):
    points = raid_data()["points"]
    top = sorted(points.items(), key=lambda kv: -kv[1])[:10]
    medals = ["🥇", "🥈", "🥉"]
    rows = [f"{medals[i] if i < 3 else f'{i + 1}.'} <@{uid}>: {pts}" for i, (uid, pts) in enumerate(top)]
    await interaction.response.send_message("🏆 **Top raiders**\n" + ("\n".join(rows) or "No raids yet: be the first! 🦧"),
                                            allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_raw_reaction_add(payload):
    """One point per raid per member for reacting with the raid emoji (honour system: X is not checked)."""
    if str(payload.emoji) != RAID["emoji"] or payload.user_id == client.user.id:
        return
    data = raid_data()
    key = f"{payload.message_id}:{payload.user_id}"
    if payload.message_id not in data["raids"] or key in data["done"]:
        return
    data["done"].append(key)
    uid = str(payload.user_id)
    data["points"][uid] = data["points"].get(uid, 0) + 1
    RAID_FILE.write_text(json.dumps(data))


@tree.command(name="setup", description="Create the OrangeOrangus server roles, channels, slowmode and rules")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def setup(interaction: discord.Interaction):
    # Second lock: even if a server setting re-enables /setup for others, only admins can run it.
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Admins only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    done = await run_setup(interaction.guild)
    await interaction.followup.send("✅ Setup complete: " + (", ".join(done) or "everything was already in place"), ephemeral=True)


async def run_setup(guild):
    try:
        return await _setup_steps(guild)
    except discord.HTTPException as e:
        print(f"⚠️ Setup stopped: {e}")
        return [f"⚠️ stopped ({e.text or e}): give the bot Administrator and move its role to the top, then retry"]


async def _setup_steps(guild):
    done = []

    roles, created = {}, set()
    for spec in CFG["roles"]:
        role = find_role(guild, spec["name"])
        if not role:
            role = await guild.create_role(name=spec["name"], colour=discord.Colour.from_str(spec["color"]),
                                           permissions=perms(spec["permissions"]), hoist=True, reason="/setup")
            created.add(role.id)
            done.append(f"role {role.name}")
        elif not role.hoist:
            # Show the role separately in the member list.
            await role.edit(hoist=True, reason="/setup")
            done.append(f"{role.name} displayed separately")
        roles[spec["name"]] = role
    # Only brand-new roles get placed (below the bot role); roles you already arranged keep their order.
    top = guild.me.top_role.position
    new = {roles[s["name"]]: max(top - 1 - i, 1) for i, s in enumerate(CFG["roles"]) if roles[s["name"]].id in created}
    if new:
        await guild.edit_role_positions(new)

    everyone = guild.default_role
    base = everyone.permissions
    base.update(mention_everyone=False, create_instant_invite=False)
    await everyone.edit(permissions=base, reason="/setup")

    staff = [roles[n] for n in CFG["staff_roles"] if n in roles]
    for cat_spec in CFG["categories"]:
        overwrites = {}
        if cat_spec.get("private"):
            overwrites = {everyone: discord.PermissionOverwrite(view_channel=False),
                          **{r: discord.PermissionOverwrite(view_channel=True) for r in staff}}
        category = find(guild.categories, cat_spec["name"])
        if not category:
            category = await guild.create_category(cat_spec["name"], overwrites=overwrites, reason="/setup")
            done.append(f"category {category.name}")
        for ch in cat_spec["channels"]:
            ow = dict(overwrites)
            if ch.get("readonly"):
                ow[everyone] = discord.PermissionOverwrite(send_messages=False)
                ow.update({r: discord.PermissionOverwrite(send_messages=True) for r in staff})
            channel = find(guild.text_channels, ch["name"])
            old = ch.get("old_name") and find(guild.text_channels, ch["old_name"])
            if not channel and old:
                # Rename the old Italian channel instead of creating a duplicate.
                await old.edit(name=ch["name"], reason="/setup")
                channel = old
                done.append(f"#{ch['old_name']} → #{ch['name']}")
            if not channel:
                channel = await guild.create_text_channel(ch["name"], category=category, overwrites=ow,
                                                          slowmode_delay=ch.get("slowmode", 0), reason="/setup")
                done.append(f"#{channel.name}")
            elif channel.slowmode_delay != ch.get("slowmode", 0):
                await channel.edit(slowmode_delay=ch.get("slowmode", 0))

    if not counter_channel(guild):
        await update_counter(guild)
        done.append("member counter")

    # Posts go after all channels exist, so every #channel and @Role mention becomes clickable.
    for name, text in CFG["channel_posts"].items():
        channel = find(guild.text_channels, name)
        if not channel:
            continue
        text = link_mentions(guild, text)
        # Oldest bot message = the info post (later bot messages in #welcome are join greetings).
        mine = [m async for m in channel.history(limit=50, oldest_first=True) if m.author == guild.me and m.type == discord.MessageType.default]
        if not mine:
            await channel.send(text, suppress_embeds=True, allowed_mentions=discord.AllowedMentions.none())
            done.append(f"#{name} post")
        elif mine[0].content != text:
            try:
                await mine[0].edit(content=text, suppress=True, allowed_mentions=discord.AllowedMentions.none())
                done.append(f"#{name} post updated")
            except discord.HTTPException as e:
                done.append(f"⚠️ #{name} post not updated ({e.text or e})")

    # Read-only channels that hold a file (e.g. the roadmap PDF): posted once.
    for name, spec in CFG.get("channel_files", {}).items():
        channel = find(guild.text_channels, name)
        path = Path(__file__).parent / spec["file"]
        if not channel or not path.exists():
            continue
        posted = [m async for m in channel.history(limit=20)
                  if m.author == guild.me and m.type == discord.MessageType.default and any(a.filename == path.name for a in m.attachments)]
        if not posted:
            await channel.send(link_mentions(guild, spec["text"]), file=discord.File(path),
                               allowed_mentions=discord.AllowedMentions.none())
            done.append(f"#{name} file")

    if guild.verification_level < discord.VerificationLevel.high:
        await guild.edit(verification_level=discord.VerificationLevel.high, reason="/setup")
        done.append("verification: High")
    given = await grant_og(guild)
    if given:
        done.append(f"OG given to {given} members")
    return done


if __name__ == "__main__":
    token_file = Path(__file__).parent / "token.txt"
    token = os.environ.get("DISCORD_TOKEN") or (token_file.read_text().strip() if token_file.exists() else "")
    if not token:
        token = input("Paste the bot token and press Enter: ").strip()
        token_file.write_text(token)
    client.run(token)
