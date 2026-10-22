"""Bot Discord OrangeOrangus: ruolo OranguTeam all'ingresso, moderazione e /setup del server.
Avvio: DISCORD_TOKEN=... python discord_bot/bot.py"""
import datetime, json, os
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
tracker = filters.Tracker(CFG["spam_messages"], CFG["spam_seconds"], CFG["duplicate_limit"])


def is_staff(member):
    return member.guild_permissions.manage_messages or any(r.name in CFG["staff_roles"] for r in member.roles)


async def log(guild, text):
    channel = discord.utils.get(guild.text_channels, name=CFG["log_channel"])
    if channel:
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_ready():
    print(f"Connesso come {client.user}")
    if not client.guilds:
        print("⚠️ Il bot non è in nessun server: invitalo con il link OAuth2 (scope bot + applications.commands).")
    # Sync per server: il comando /setup compare subito, senza attese.
    for guild in client.guilds:
        try:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"✅ /setup pronto nel server {guild.name} (in alternativa scrivi !setup)")
        except discord.HTTPException as e:
            print(f"⚠️ {guild.name}: /setup non registrato ({e}). Reinvita il bot con lo scope applications.commands, "
                  "oppure scrivi !setup nel server.")


@client.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name=CFG["join_role"])
    if role:
        await member.add_roles(role, reason="Ruolo automatico all'ingresso")
    else:
        await log(member.guild, f"⚠️ Ruolo {CFG['join_role']} non trovato: esegui /setup")


@client.event
async def on_message(message):
    if message.guild and message.content.strip() == "!setup" and message.author.guild_permissions.administrator:
        await message.channel.send("⏳ Setup in corso...")
        done = await run_setup(message.guild)
        await message.channel.send("✅ Setup completato: " + (", ".join(done) or "era già tutto a posto"))
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
    action = "messaggio eliminato"
    if timeout:
        try:
            await message.author.timeout(datetime.timedelta(minutes=CFG["timeout_minutes"]), reason=reason)
            action += f" + timeout {CFG['timeout_minutes']} min"
        except discord.HTTPException:
            action += " (timeout non riuscito: controlla i permessi del bot)"
    await message.channel.send(f"🦧 {message.author.mention}, {reason}. Leggi #regole.", delete_after=10)
    await log(message.guild, f"🛡️ {message.author} in #{message.channel}: {reason} → {action}\n> {message.content[:300]}")


def perms(names):
    return discord.Permissions(**{n: True for n in names})


@tree.command(name="setup", description="Crea ruoli, canali, slowmode e regole del server OrangeOrangus")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    done = await run_setup(interaction.guild)
    await interaction.followup.send("✅ Setup completato: " + (", ".join(done) or "era già tutto a posto"), ephemeral=True)


async def run_setup(guild):
    try:
        return await _setup_steps(guild)
    except discord.HTTPException as e:
        print(f"⚠️ Setup interrotto: {e}")
        return [f"⚠️ interrotto ({e.text or e}): dai al bot il permesso Amministratore e mettilo in cima ai ruoli, poi riprova"]


async def _setup_steps(guild):
    done = []

    roles = {}
    for spec in CFG["roles"]:
        role = discord.utils.get(guild.roles, name=spec["name"])
        if not role:
            role = await guild.create_role(name=spec["name"], colour=discord.Colour.from_str(spec["color"]),
                                           permissions=perms(spec["permissions"]), reason="/setup")
            done.append(f"ruolo {role.name}")
        roles[spec["name"]] = role
    # Ordine dall'alto: Founder, Mod, OranguTeam (tutti sotto il ruolo del bot).
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
            done.append(f"categoria {category.name}")
        for ch in cat_spec["channels"]:
            ow = dict(overwrites)
            if ch.get("readonly"):
                ow[everyone] = discord.PermissionOverwrite(send_messages=False)
                ow.update({r: discord.PermissionOverwrite(send_messages=True) for r in staff})
            channel = discord.utils.get(guild.text_channels, name=ch["name"])
            if not channel:
                channel = await guild.create_text_channel(ch["name"], category=category, overwrites=ow,
                                                          slowmode_delay=ch.get("slowmode", 0), reason="/setup")
                done.append(f"#{channel.name}")
            elif channel.slowmode_delay != ch.get("slowmode", 0):
                await channel.edit(slowmode_delay=ch.get("slowmode", 0))
            if ch["name"] == "regole" and not [m async for m in channel.history(limit=1)]:
                await channel.send(CFG["rules_text"])
                done.append("testo #regole")

    if guild.verification_level < discord.VerificationLevel.high:
        await guild.edit(verification_level=discord.VerificationLevel.high, reason="/setup")
        done.append("verifica: Alta")
    return done


if __name__ == "__main__":
    token_file = Path(__file__).parent / "token.txt"
    token = os.environ.get("DISCORD_TOKEN") or (token_file.read_text().strip() if token_file.exists() else "")
    if not token:
        token = input("Incolla il token del bot e premi Invio: ").strip()
        token_file.write_text(token)
    client.run(token)
