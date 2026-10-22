"""OrangeOrangus Discord bot: OranguTeam join role, moderation and server /setup.
Run: DISCORD_TOKEN=... python discord_bot/bot.py"""
import datetime, json, os, re
from pathlib import Path

import discord
from discord import app_commands

import filters

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
OG_FILE = Path(__file__).parent / "og_members.json"
tracker = filters.Tracker(CFG["spam_messages"], CFG["spam_seconds"], CFG["duplicate_limit"])


def is_staff(member):
    return member.guild_permissions.manage_messages or any(r.name in CFG["staff_roles"] for r in member.roles)


async def log(guild, text):
    channel = discord.utils.get(guild.text_channels, name=CFG["log_channel"])
    if channel:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_ready():
    print(f"Connected as {client.user}")
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


async def grant_og(guild):
    """Gives OG to the first og_limit members by join date. Saved to og_members.json so it survives restarts."""
    role = discord.utils.get(guild.roles, name=CFG["og_role"])
    if not role:
        return 0
    granted = set(json.loads(OG_FILE.read_text())) if OG_FILE.exists() else set()
    granted |= {m.id for m in role.members}
    humans = sorted((m for m in guild.members if not m.bot), key=lambda m: m.joined_at or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc))
    picks = filters.og_picks(granted, [m.id for m in humans], CFG["og_limit"])
    given = 0
    for member_id in picks:
        try:
            await guild.get_member(member_id).add_roles(role, reason=f"First {CFG['og_limit']} members")
        except discord.HTTPException as e:
            print(f"⚠️ Could not give OG ({e}): move the bot role above OG.")
            break
        granted.add(member_id)
        given += 1
    OG_FILE.write_text(json.dumps(sorted(granted)))
    return given


@client.event
async def on_member_join(member):
    if not member.bot:
        await grant_og(member.guild)
    role = discord.utils.get(member.guild.roles, name=CFG["join_role"])
    if role:
        await member.add_roles(role, reason="Automatic join role")
    else:
        await log(member.guild, f"⚠️ Role {CFG['join_role']} not found: run /setup")
    welcome = discord.utils.get(member.guild.text_channels, name="welcome")
    if welcome and not member.bot:
        text = CFG["welcome_message"].format(member=member.mention, count=member.guild.member_count)
        await welcome.send(link_mentions(member.guild, text), allowed_mentions=discord.AllowedMentions(users=True))


@client.event
async def on_message(message):
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
        ch = discord.utils.get(guild.text_channels, name=m.group(1))
        return ch.mention if ch else m.group(0)

    def role(m):
        r = discord.utils.get(guild.roles, name=m.group(1))
        return r.mention if r else m.group(0)

    text = re.sub(r"#([a-z0-9-]+)", channel, text)
    return re.sub(r"@([A-Za-z]+)", role, text)


async def server_invite(guild):
    """Reuses the bot's permanent invite, or creates one on #welcome."""
    for invite in await guild.invites():
        if invite.inviter == guild.me and not invite.max_age:
            return invite.url
    channel = discord.utils.get(guild.text_channels, name="welcome") or guild.text_channels[0]
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

    roles = {}
    for spec in CFG["roles"]:
        role = discord.utils.get(guild.roles, name=spec["name"])
        if not role:
            role = await guild.create_role(name=spec["name"], colour=discord.Colour.from_str(spec["color"]),
                                           permissions=perms(spec["permissions"]), hoist=True, reason="/setup")
            done.append(f"role {role.name}")
        elif not role.hoist:
            # Show the role separately in the member list.
            await role.edit(hoist=True, reason="/setup")
            done.append(f"{role.name} displayed separately")
        roles[spec["name"]] = role
    # Order from the top: Founder, Mod, OranguTeam (all below the bot role).
    top = guild.me.top_role.position
    await guild.edit_role_positions({roles[s["name"]]: max(top - 1 - i, 1) for i, s in enumerate(CFG["roles"])})

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
        category = discord.utils.get(guild.categories, name=cat_spec["name"])
        if not category:
            category = await guild.create_category(cat_spec["name"], overwrites=overwrites, reason="/setup")
            done.append(f"category {category.name}")
        for ch in cat_spec["channels"]:
            ow = dict(overwrites)
            if ch.get("readonly"):
                ow[everyone] = discord.PermissionOverwrite(send_messages=False)
                ow.update({r: discord.PermissionOverwrite(send_messages=True) for r in staff})
            channel = discord.utils.get(guild.text_channels, name=ch["name"])
            old = ch.get("old_name") and discord.utils.get(guild.text_channels, name=ch["old_name"])
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

    # Posts go after all channels exist, so every #channel and @Role mention becomes clickable.
    for name, text in CFG["channel_posts"].items():
        channel = discord.utils.get(guild.text_channels, name=name)
        if not channel:
            continue
        text = link_mentions(guild, text)
        # Oldest bot message = the info post (later bot messages in #welcome are join greetings).
        mine = [m async for m in channel.history(limit=50, oldest_first=True) if m.author == guild.me]
        if not mine:
            await channel.send(text, suppress_embeds=True, allowed_mentions=discord.AllowedMentions.none())
            done.append(f"#{name} post")
        elif mine[0].content != text:
            await mine[0].edit(content=text, suppress=True, allowed_mentions=discord.AllowedMentions.none())
            done.append(f"#{name} post updated")

    # Read-only channels that hold a file (e.g. the roadmap PDF): posted once.
    for name, spec in CFG.get("channel_files", {}).items():
        channel = discord.utils.get(guild.text_channels, name=name)
        path = Path(__file__).parent / spec["file"]
        if not channel or not path.exists():
            continue
        posted = [m async for m in channel.history(limit=20)
                  if m.author == guild.me and any(a.filename == path.name for a in m.attachments)]
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
