import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import pytz
import json
import os
import re

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID")  # <-- deine Server-ID hier als Railway Variable eintragen!
TIMEZONE = pytz.timezone("Europe/Berlin")
EMBED_COLOR = 0x3B82F6  # Blau
DATA_DIR = "/data" if os.path.isdir("/data") else "."
DATA_FILE = os.path.join(DATA_DIR, "data.json")

# ─── STANDARD-KONFIGURATION ────────────────────────────────────────────────────
# Diese Werte werden beim allerersten Start automatisch übernommen (bzw. immer
# dann, wenn der jeweilige Wert noch nicht gesetzt ist). Über die passenden
# Slash-Commands (z.B. /setrolle, /set_aufstellung, ...) kannst du sie jederzeit
# überschreiben - die Änderung bleibt dann dauerhaft gespeichert.
STANDARD_KONFIG = {
    "leitung_rolle_id": "1531669388841980031",
    "rolle_id": "1531669388821004337",

    "channel_aufstellung": 1531669392847540381,
    "channel_archiv": 1531676938551300287,

    "channel_abmeldung": 1531676692676874310,
    "channel_abmeldung_liste": 1531669393627549711,
    "channel_abmeldung_button": 1531669394114220083,

    "channel_verifizierung": 1531674115314946149,
    "channel_verifizierung_log": 1531675872669602006,

    "channel_probewoche_erinnerung": 1531676318536826970,

    "rollen_nach_verifizierung": {
        "Probezeit": "1531676136373747915",
        "Homies": "1531669388821004337",
        "01 - Runner": "1531669388871078012",
        "Wochenabgabe": "1531680977120919613",
    },

    # Welcome/Leave ("Blood in" / "Blood out")
    "channel_blood_in": 1531669392847540375,
    "channel_blood_out": 1531669392847540376,
}

# Leitungs-Rolle: darf ALLES bearbeiten (wie Admin), auch ohne die Discord-
# Server-Berechtigung "Administrator". Wird per /set_leitung gesetzt.
def ist_admin_oder_leitung(interaction: discord.Interaction) -> bool:
    """True für echte Admins ODER Mitglieder mit der Leitungs-Rolle.
    Wird als Ersatz für app_commands.checks.has_permissions(administrator=True)
    bei allen Admin-Befehlen verwendet."""
    if interaction.user.guild_permissions.administrator:
        return True
    leitung_rolle_id = data.get("leitung_rolle_id")
    if not leitung_rolle_id:
        return False
    return any(str(r.id) == str(leitung_rolle_id) for r in interaction.user.roles)

# ─── DATA HANDLER ─────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            geladen = json.load(f)
    else:
        geladen = {}

    standard = {
        "leitung_rolle_id": None,
        "rolle_id": None,
        "aktuelle_nachricht_id": None,
        "abstimmung": {},
        "abmeldungen": {},
        "eingefroren": False,
        "aktuelles_datum": None,
        "channel_aufstellung": None,
        "channel_archiv": None,
        "channel_abmeldung": None,
        "channel_abmeldung_liste": None,
        "abmeldung_liste_nachricht_id": None,
        "channel_abmeldung_button": None,
        "abmeldung_button_nachricht_id": None,
        "aufstellung_tage_config": {str(i): {"aktiv": False, "uhrzeit": "20:00"} for i in range(7)},
        "aktueller_wochentag": None,
        "channel_verifizierung": None,
        "verifizierung_nachricht_id": None,
        "channel_verifizierung_log": None,
        "channel_probewoche_erinnerung": None,
        "verifizierungen": {},
        "rollen_nach_verifizierung": {},  # { "Anzeigename": "rolle_id" } - per /set_verifizierungsrolle
        "channel_blood_in": None,
        "channel_blood_out": None,
        "geplante_aufstellung_loeschungen": [],
    }

    # Grund-Struktur sicherstellen (fehlende Keys ergänzen)
    for key, wert in standard.items():
        geladen.setdefault(key, wert)

    # Vorausgefüllte Standard-IDs übernehmen, aber NUR für Werte, die noch
    # nicht gesetzt sind (None / leer). Einmal per Command gesetzte Werte
    # werden dadurch nie wieder überschrieben.
    for key, wert in STANDARD_KONFIG.items():
        if not geladen.get(key):
            geladen[key] = wert

    return geladen

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()
save_data(data)  # sorgt dafür, dass die vorausgefüllten Werte sofort persistiert werden

# ─── BOT SETUP ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── HILFSFUNKTIONEN ──────────────────────────────────────────────────────────
WOCHENTAGE_NAMEN = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
WOCHENTAGE_MAP = {name.lower(): i for i, name in enumerate(WOCHENTAGE_NAMEN)}

# Anzeigenamen der Rollen, die nach der Verifizierung vergeben werden sollen.
VERIFIZIERUNGS_ROLLEN_NAMEN = ["Probezeit", "Homies", "01 - Runner", "Wochenabgabe"]

def get_morgen_datum():
    now = datetime.now(TIMEZONE)
    morgen = now + timedelta(days=1)
    wochentage = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    return f"{wochentage[morgen.weekday()]}, {morgen.strftime('%d.%m.%Y')}"

def get_heute_datum():
    now = datetime.now(TIMEZONE)
    wochentage = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    return f"{wochentage[now.weekday()]}, {now.strftime('%d.%m.%Y')}"

async def get_rolle_mitglieder(guild):
    rolle_id = data.get("rolle_id")
    if not rolle_id:
        return []
    rolle = guild.get_role(int(rolle_id))
    if not rolle:
        return []
    return [m for m in rolle.members if not m.bot]

# ─── DATUMS-HILFSFUNKTIONEN (Abmeldungen) ─────────────────────────────────────
DATUM_REGEX = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$")

def parse_datum(datum_str):
    """Parst ein Datum im Format TT.MM.JJJJ oder TT.MM.JJ (auch ohne führende
    Nullen), sonst None. Ein 2-stelliges Jahr wird als 20XX interpretiert."""
    m = DATUM_REGEX.match(str(datum_str).strip())
    if not m:
        return None
    tag, monat, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if jahr < 100:
        jahr += 2000
    try:
        return datetime(jahr, monat, tag)
    except ValueError:
        return None

def ist_abmeldung_aktiv(info):
    """True, wenn der abgemeldete Zeitraum HEUTE bereits läuft (von <= heute <= bis).
    Kann eines der Daten nicht ausgewertet werden, wird sicherheitshalber
    'aktiv' angenommen (altes Verhalten), damit nichts verloren geht."""
    heute = datetime.now(TIMEZONE).date()
    von_datum = parse_datum(info.get("von", ""))
    bis_datum = parse_datum(info.get("bis", ""))
    if von_datum and bis_datum:
        return von_datum.date() <= heute <= bis_datum.date()
    return True

def build_embed(datum, mitglieder, eingefroren=False):
    abstimmung  = data.get("abstimmung", {})
    abmeldungen = data.get("abmeldungen", {})

    wochentag   = data.get("aktueller_wochentag")
    tage_config = data.get("aufstellung_tage_config", {})
    anzeige_zeit = tage_config.get(str(wochentag), {}).get("uhrzeit", "21:00") if wochentag is not None else "21:00"

    ja_liste        = []
    spaeter_liste   = []
    nein_liste      = []
    abgemeldet_liste= []
    offen_liste     = []

    for m in mitglieder:
        uid     = str(m.id)
        mention = m.mention
        abmeldung_info = abmeldungen.get(uid)
        # Wer trotz Abmeldung aktiv abgestimmt hat, soll auch als das gezählt
        # werden, was er/sie gewählt hat — die Abmeldung blockiert das
        # Reagieren NICHT.
        if uid in abstimmung:
            status = abstimmung[uid]
            if status == "ja":
                ja_liste.append(mention)
            elif status == "spaeter":
                spaeter_liste.append(mention)
            elif status == "nein":
                nein_liste.append(mention)
        elif abmeldung_info and ist_abmeldung_aktiv(abmeldung_info):
            abgemeldet_liste.append(mention)
        else:
            offen_liste.append(mention)

    titel = "Meet Up"
    if eingefroren:
        titel += " *(Eingefroren)*"

    embed = discord.Embed(
        title=titel,
        description=(
            f"**{datum}**\n"
            f"Meet Up: **{anzeige_zeit} Uhr**\n"
            f"{'🔒 Abstimmung geschlossen!' if eingefroren else '✅ Jetzt abstimmen!'}"
        ),
        color=EMBED_COLOR
    )

    embed.add_field(
        name=f"Komme ({len(ja_liste)})",
        value="\n".join(ja_liste) if ja_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"Komme später ({len(spaeter_liste)})",
        value="\n".join(spaeter_liste) if spaeter_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"Komme nicht ({len(nein_liste)})",
        value="\n".join(nein_liste) if nein_liste else "*Niemand*",
        inline=True
    )
    embed.add_field(
        name=f"Abgemeldet ({len(abgemeldet_liste)})",
        value="\n".join(abgemeldet_liste) if abgemeldet_liste else "*Niemand*",
        inline=True
    )

    if offen_liste:
        label = "Nicht gemeldet" if eingefroren else "Noch nicht abgestimmt"
        embed.add_field(
            name=f"{label} ({len(offen_liste)})",
            value="\n".join(offen_liste),
            inline=False
        )

    embed.set_footer(text="Blue End")
    embed.timestamp = datetime.now(TIMEZONE)
    return embed

# ─── VIEWS (BUTTONS) ──────────────────────────────────────────────────────────
class AufstellungView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check_berechtigung(self, interaction: discord.Interaction):
        if data.get("eingefroren"):
            await interaction.response.send_message(
                "Die Abstimmung ist bereits geschlossen!", ephemeral=True
            )
            return False
        rolle_id = data.get("rolle_id")
        if not rolle_id:
            await interaction.response.send_message(
                "Keine Rolle gesetzt. Admin: /setrolle benutzen.", ephemeral=True
            )
            return False
        rolle = interaction.guild.get_role(int(rolle_id))
        if rolle not in interaction.user.roles:
            await interaction.response.send_message(
                "Du hast keine Berechtigung für diese Abstimmung.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Komme", style=discord.ButtonStyle.success, custom_id="btn_ja")
    async def btn_ja(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "ja"
        save_data(data)
        await update_nachricht(interaction.guild)
        await interaction.response.send_message("Du hast mit **Komme** abgestimmt!", ephemeral=True)

    @discord.ui.button(label="Komme später", style=discord.ButtonStyle.secondary, custom_id="btn_spaeter")
    async def btn_spaeter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "spaeter"
        save_data(data)
        await update_nachricht(interaction.guild)
        await interaction.response.send_message("Du hast mit **Komme später** abgestimmt!", ephemeral=True)

    @discord.ui.button(label="Komme nicht", style=discord.ButtonStyle.danger, custom_id="btn_nein")
    async def btn_nein(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_berechtigung(interaction):
            return
        data["abstimmung"][str(interaction.user.id)] = "nein"
        save_data(data)
        await update_nachricht(interaction.guild)
        await interaction.response.send_message("Du hast mit **Komme nicht** abgestimmt!", ephemeral=True)

# ─── ABMELDUNG PER BUTTON + MODAL ─────────────────────────────────────────────
class AbmeldungModal(discord.ui.Modal, title="Abmeldung"):
    name_input = discord.ui.TextInput(
        label="Name", placeholder="Wer meldet sich ab?", required=True, max_length=32
    )
    von_input = discord.ui.TextInput(
        label="Von wann? (TT.MM.JJJJ)", placeholder="14.07.2026", required=True, max_length=32
    )
    bis_input = discord.ui.TextInput(
        label="Bis wann? (TT.MM.JJJJ)", placeholder="16.07.2026", required=True, max_length=32
    )
    grund_input = discord.ui.TextInput(
        label="Begründung", placeholder="Grund der Abmeldung", required=True,
        max_length=300, style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        rolle_id = data.get("rolle_id")
        if rolle_id:
            rolle = interaction.guild.get_role(int(rolle_id))
            if rolle and rolle not in interaction.user.roles:
                await interaction.response.send_message(
                    "Du hast keine Berechtigung zur Abmeldung.", ephemeral=True
                )
                return

        name  = self.name_input.value.strip()
        von   = self.von_input.value.strip()
        bis   = self.bis_input.value.strip()
        grund = self.grund_input.value.strip()

        von_datum = parse_datum(von)
        bis_datum = parse_datum(bis)
        if not von_datum or not bis_datum:
            await interaction.response.send_message(
                "❌ Ungültiges Datumsformat. Bitte **TT.MM.JJJJ** verwenden, z.B. `14.07.2026`.",
                ephemeral=True
            )
            return
        if bis_datum < von_datum:
            await interaction.response.send_message(
                "❌ Das Enddatum darf nicht vor dem Startdatum liegen.", ephemeral=True
            )
            return

        von, bis = von_datum.strftime("%d.%m.%Y"), bis_datum.strftime("%d.%m.%Y")

        uid = str(interaction.user.id)
        data["abmeldungen"][uid] = {"name": name, "von": von, "bis": bis, "grund": grund, "typ": "kurzzeit"}
        save_data(data)

        if not data.get("eingefroren"):
            await update_nachricht(interaction.guild)
        await update_abmeldung_liste(interaction.guild)

        aktiv_hinweis = "" if ist_abmeldung_aktiv(data["abmeldungen"][uid]) else \
            "\nℹ️ Dein Zeitraum beginnt erst später – bis dahin wirst du weiterhin normal im Meet Up geführt und kannst abstimmen."
        await interaction.response.send_message(
            f"✅ Abmeldung eingetragen!\n"
            f"Name: **{name}**\n"
            f"Von: **{von}**\n"
            f"Bis: **{bis}**{aktiv_hinweis}",
            ephemeral=True
        )

        if data.get("channel_abmeldung"):
            abm_kanal = interaction.guild.get_channel(int(data["channel_abmeldung"]))
            if abm_kanal:
                embed_abm = discord.Embed(title="Neue Abmeldung", color=EMBED_COLOR)
                embed_abm.add_field(name="Name",     value=name,                     inline=True)
                embed_abm.add_field(name="Mitglied", value=interaction.user.mention, inline=True)
                embed_abm.add_field(name="Von",      value=von,                      inline=True)
                embed_abm.add_field(name="Bis",      value=bis,                      inline=True)
                embed_abm.add_field(name="Grund",    value=grund,                    inline=False)
                embed_abm.set_footer(text="Blue End")
                embed_abm.timestamp = datetime.now(TIMEZONE)
                await abm_kanal.send(embed=embed_abm)

class AbmeldungButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abmeldung", style=discord.ButtonStyle.danger, custom_id="btn_abmeldung_oeffnen")
    async def btn_abmeldung(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AbmeldungModal())

async def abmeldung_button_posten_intern(guild):
    if not data.get("channel_abmeldung_button"):
        return
    kanal = guild.get_channel(int(data["channel_abmeldung_button"]))
    if not kanal:
        return

    embed = discord.Embed(
        title="Abmeldung",
        description="Klick auf den Button unten, um dich abzumelden. Du trägst Name, Zeitraum und Grund ein.",
        color=EMBED_COLOR
    )
    embed.set_footer(text="Blue End")
    view = AbmeldungButtonView()

    msg_id = data.get("abmeldung_button_nachricht_id")
    if msg_id:
        try:
            msg = await kanal.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return
        except Exception as e:
            print(f"Alte Abmeldung-Button-Nachricht nicht gefunden, poste neu: {e}")

    msg = await kanal.send(embed=embed, view=view)
    data["abmeldung_button_nachricht_id"] = str(msg.id)
    save_data(data)

# ─── VERIFIZIERUNG (IC-Name, Nummer, Probewoche) ─────────────────────────────
class VerifizierungModal(discord.ui.Modal, title="Verifizierung: IC-Name & Nummer"):
    ic_name = discord.ui.TextInput(
        label="Dein In-Character Name", placeholder="Max Mustermann", required=True, max_length=32
    )
    ic_nummer = discord.ui.TextInput(
        label="Deine IC-Telefonnummer", placeholder="Einfach vom Handy kopieren", required=True, max_length=20
    )
    geworben_von = discord.ui.TextInput(
        label="Angeworben von (Optional)", placeholder="Name des Mitglieds das dich angeworben hat",
        required=False, max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        verifizierungen = data.setdefault("verifizierungen", {})
        verifizierungen[uid] = {
            "ic_name": self.ic_name.value.strip(),
            "ic_nummer": self.ic_nummer.value.strip(),
            "geworben_von": self.geworben_von.value.strip() if self.geworben_von.value else None,
            "verifiziert_am": datetime.now(TIMEZONE).isoformat(),
            "erinnert": False
        }
        save_data(data)

        rollen_config = data.get("rollen_nach_verifizierung", {})
        nicht_vergeben = []
        for name in VERIFIZIERUNGS_ROLLEN_NAMEN:
            rolle_id = rollen_config.get(name)
            if not rolle_id:
                nicht_vergeben.append(f"{name} (nicht konfiguriert – /set_verifizierungsrolle benutzen)")
                continue
            rolle = interaction.guild.get_role(int(rolle_id))
            if not rolle:
                nicht_vergeben.append(f"{name} (Rolle nicht gefunden)")
                continue
            try:
                await interaction.user.add_roles(rolle)
            except discord.Forbidden:
                nicht_vergeben.append(f"{name} (keine Berechtigung)")

        name_fehler = None
        try:
            await interaction.user.edit(nick=self.ic_name.value.strip())
        except discord.Forbidden:
            name_fehler = (
                "Servername konnte nicht geändert werden (keine Berechtigung – "
                "z.B. bei Server-Inhaber:innen oder wenn deine höchste Rolle über der Bot-Rolle liegt)."
            )
        except Exception as e:
            name_fehler = f"Servername konnte nicht geändert werden: {e}"

        antwort = "✅ Verifizierung abgeschlossen! Deine Probewoche beginnt jetzt."
        if nicht_vergeben:
            antwort += "\n⚠️ Diese Rollen konnten nicht vergeben werden: " + ", ".join(nicht_vergeben)
        if name_fehler:
            antwort += f"\n⚠️ {name_fehler}"
        await interaction.response.send_message(antwort, ephemeral=True)

        if data.get("channel_verifizierung_log"):
            log_kanal = interaction.guild.get_channel(int(data["channel_verifizierung_log"]))
            if log_kanal:
                embed = discord.Embed(title="Neue Verifizierung", color=EMBED_COLOR)
                embed.add_field(name="Discord",   value=interaction.user.mention,        inline=True)
                embed.add_field(name="IC-Name",   value=self.ic_name.value,              inline=True)
                embed.add_field(name="IC-Nummer", value=f"**{self.ic_nummer.value}**",   inline=True)
                if self.geworben_von.value:
                    embed.add_field(name="Angeworben von", value=f"**{self.geworben_von.value}**", inline=True)
                embed.set_footer(text="Blue End")
                embed.timestamp = datetime.now(TIMEZONE)
                await log_kanal.send(embed=embed)

class VerifizierungButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.success, custom_id="btn_verifizierung_oeffnen")
    async def btn_verifizieren(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerifizierungModal())

async def verifizierung_posten_intern(guild):
    if not data.get("channel_verifizierung"):
        return
    kanal = guild.get_channel(int(data["channel_verifizierung"]))
    if not kanal:
        return

    embed = discord.Embed(
        title="Verifizierung",
        description="Klicke auf **Verifizieren**, um deinen IC-Namen und deine Nummer einzugeben. Danach beginnt deine Probewoche!",
        color=EMBED_COLOR
    )
    embed.set_footer(text="Blue End")
    view = VerifizierungButtonView()

    msg_id = data.get("verifizierung_nachricht_id")
    if msg_id:
        try:
            msg = await kanal.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            return
        except Exception as e:
            print(f"Alte Verifizierungs-Nachricht nicht gefunden, poste neu: {e}")

    msg = await kanal.send(embed=embed, view=view)
    data["verifizierung_nachricht_id"] = str(msg.id)
    save_data(data)

async def update_nachricht(guild):
    msg_id = data.get("aktuelle_nachricht_id")
    if not msg_id or not data.get("channel_aufstellung"):
        return
    kanal = guild.get_channel(int(data["channel_aufstellung"]))
    if not kanal:
        return
    try:
        msg        = await kanal.fetch_message(int(msg_id))
        mitglieder = await get_rolle_mitglieder(guild)
        datum      = data.get("aktuelles_datum", get_morgen_datum())
        embed      = build_embed(datum, mitglieder, data.get("eingefroren", False))
        await msg.edit(embed=embed)
    except Exception as e:
        print(f"Fehler beim Update der Nachricht: {e}")

# ─── ABMELDUNGS-ÜBERSICHT (persistente Liste) ────────────────────────────────
def build_abmeldung_liste_embed(guild):
    abmeldungen = data.get("abmeldungen", {})
    embed = discord.Embed(
        title="Abmeldungs-Übersicht",
        color=EMBED_COLOR
    )

    if not abmeldungen:
        embed.description = "*Aktuell ist niemand abgemeldet.*"
        embed.set_footer(text="Blue End")
        embed.timestamp = datetime.now(TIMEZONE)
        return embed

    def sort_key(item):
        _, info = item
        parsed = parse_datum(info.get("bis", ""))
        return (parsed is None, parsed or datetime.max)

    sortierte_abmeldungen = sorted(abmeldungen.items(), key=sort_key)

    bloecke = []
    for uid, info in sortierte_abmeldungen:
        member  = guild.get_member(int(uid))
        name    = info.get("name") or (member.display_name if member else f"Unbekanntes Mitglied ({uid})")
        mention = member.mention if member else f"<@{uid}>"

        typ       = info.get("typ", "kurzzeit")
        typ_label = "🕐 Langzeit" if typ == "langzeit" else "📅 Kurzzeit"
        von       = info.get("von", "-")
        bis       = info.get("bis", "-")
        grund     = info.get("grund", "-")
        status    = "🟢 Aktiv" if ist_abmeldung_aktiv(info) else "⏳ Bevorstehend"

        block = (
            f"{mention}  ·  {typ_label}  ·  {status}\n"
            f"Name: **{name}**\n"
            f"Von: **{von}**  Bis: **{bis}**\n"
            f"Grund: {grund}"
        )
        bloecke.append(block)

    embed.description = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(bloecke)
    embed.set_footer(text="Blue End")
    embed.timestamp = datetime.now(TIMEZONE)
    return embed

async def update_abmeldung_liste(guild):
    if not data.get("channel_abmeldung_liste"):
        return
    kanal = guild.get_channel(int(data["channel_abmeldung_liste"]))
    if not kanal:
        return
    embed  = build_abmeldung_liste_embed(guild)
    msg_id = data.get("abmeldung_liste_nachricht_id")
    if msg_id:
        try:
            msg = await kanal.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
            return
        except Exception as e:
            print(f"Abmeldungs-Liste Nachricht nicht gefunden, poste neu: {e}")
    msg = await kanal.send(embed=embed)
    data["abmeldung_liste_nachricht_id"] = str(msg.id)
    save_data(data)

async def abgelaufene_abmeldungen_aufraeumen():
    """Entfernt alle Abmeldungen, deren 'Bis'-Datum bereits vergangen ist.
    Gibt die Liste der entfernten User-IDs zurück."""
    abmeldungen = data.get("abmeldungen", {})
    heute = datetime.now(TIMEZONE).date()
    entfernte_uids = []
    for uid, info in list(abmeldungen.items()):
        bis_datum = parse_datum(info.get("bis", ""))
        if bis_datum and bis_datum.date() < heute:
            del abmeldungen[uid]
            entfernte_uids.append(uid)
    if entfernte_uids:
        save_data(data)
    return entfernte_uids

# ─── ALTE AUFSTELLUNGS-NACHRICHT: VERZÖGERTE LÖSCHUNG (1h) ───────────────────
async def alte_aufstellungen_aufraeumen():
    """Löscht alte Aufstellungs-Nachrichten, deren geplante Löschzeit erreicht
    ist. Das Archiv (channel_archiv) wird hiervon NIE berührt, da dort eine
    komplett eigene Nachricht in einem eigenen Channel liegt."""
    geplante = data.get("geplante_aufstellung_loeschungen", [])
    if not geplante:
        return
    now = datetime.now(TIMEZONE)
    verbleibend = []
    for eintrag in geplante:
        try:
            faellig = datetime.fromisoformat(eintrag["loeschen_um"])
        except Exception:
            continue
        if now < faellig:
            verbleibend.append(eintrag)
            continue
        geloescht = False
        for guild in bot.guilds:
            kanal = guild.get_channel(int(eintrag["channel_id"]))
            if not kanal:
                continue
            try:
                msg = await kanal.fetch_message(int(eintrag["message_id"]))
                await msg.delete()
            except Exception:
                pass
            geloescht = True
            break
        if not geloescht:
            verbleibend.append(eintrag)
    if len(verbleibend) != len(geplante):
        data["geplante_aufstellung_loeschungen"] = verbleibend
        save_data(data)

# ─── NEUE ABSTIMMUNG POSTEN ───────────────────────────────────────────────────
async def neue_abstimmung_posten(guild, manual_channel=None, verwende_heute=False):
    if manual_channel:
        kanal = manual_channel
    elif data.get("channel_aufstellung"):
        kanal = guild.get_channel(int(data["channel_aufstellung"]))
    else:
        print("Kein Meet Up-Channel gesetzt! Bitte /set_aufstellung benutzen.")
        return

    if not kanal:
        print("Meet Up-Channel nicht gefunden!")
        return

    alte_msg_id = data.get("aktuelle_nachricht_id")
    if alte_msg_id:
        geplante = data.setdefault("geplante_aufstellung_loeschungen", [])
        geplante.append({
            "channel_id": kanal.id,
            "message_id": alte_msg_id,
            "loeschen_um": (datetime.now(TIMEZONE) + timedelta(hours=1)).isoformat()
        })
        save_data(data)

    datum = get_heute_datum() if verwende_heute else get_morgen_datum()
    ziel_zeitpunkt = datetime.now(TIMEZONE) if verwende_heute else (datetime.now(TIMEZONE) + timedelta(days=1))
    data["abstimmung"]          = {}
    data["eingefroren"]         = False
    data["aktuelles_datum"]     = datum
    data["aktueller_wochentag"] = ziel_zeitpunkt.weekday()

    mitglieder = await get_rolle_mitglieder(guild)

    embed = build_embed(datum, mitglieder, eingefroren=False)
    view  = AufstellungView()

    rolle_id = data.get("rolle_id")
    ping_text = None
    if rolle_id:
        rolle = guild.get_role(int(rolle_id))
        if rolle:
            ping_text = rolle.mention

    msg = await kanal.send(content=ping_text, embed=embed, view=view)
    data["aktuelle_nachricht_id"] = str(msg.id)
    save_data(data)
    print(f"Neue Abstimmung gepostet für {datum}")

# ─── ABSTIMMUNG EINFRIEREN & ARCHIVIEREN ─────────────────────────────────────
async def abstimmung_einfrieren(guild):
    data["eingefroren"] = True
    save_data(data)

    mitglieder = await get_rolle_mitglieder(guild)
    datum      = data.get("aktuelles_datum", get_heute_datum())

    if data.get("channel_aufstellung"):
        kanal  = guild.get_channel(int(data["channel_aufstellung"]))
        msg_id = data.get("aktuelle_nachricht_id")
        if kanal and msg_id:
            try:
                msg   = await kanal.fetch_message(int(msg_id))
                embed = build_embed(datum, mitglieder, eingefroren=True)
                await msg.edit(embed=embed, view=None)
            except Exception as e:
                print(f"Fehler beim Einfrieren: {e}")

    if data.get("channel_archiv"):
        archiv = guild.get_channel(int(data["channel_archiv"]))
        if archiv:
            embed_archiv       = build_embed(datum, mitglieder, eingefroren=True)
            embed_archiv.title = f"ARCHIV – {embed_archiv.title}"
            await archiv.send(embed=embed_archiv)
            print(f"Abstimmung archiviert für {datum}")

# ─── PROBEWOCHE-ERINNERUNG ────────────────────────────────────────────────────
async def check_probewoche_erinnerungen():
    if not data.get("channel_probewoche_erinnerung"):
        return
    verifizierungen = data.get("verifizierungen", {})
    if not verifizierungen:
        return

    now = datetime.now(TIMEZONE)
    geaendert = False
    for uid, info in verifizierungen.items():
        if info.get("erinnert"):
            continue
        try:
            verifiziert_am = datetime.fromisoformat(info["verifiziert_am"])
        except Exception:
            continue
        if now - verifiziert_am >= timedelta(days=7):
            for guild in bot.guilds:
                kanal = guild.get_channel(int(data["channel_probewoche_erinnerung"]))
                if kanal:
                    try:
                        await kanal.send(
                            f"⏰ **Probewoche abgelaufen:** <@{uid}> "
                            f"(IC-Name: **{info.get('ic_name', '-')}**) hat seine 7-tägige "
                            f"Probewoche beendet. Bitte prüfen und ggf. befördern."
                        )
                    except Exception as e:
                        print(f"Fehler beim Senden der Probewoche-Erinnerung: {e}")
            info["erinnert"] = True
            geaendert = True

    if geaendert:
        save_data(data)

# ─── WELCOME / LEAVE ("Blood in" / "Blood out") ──────────────────────────────
async def sende_welcome_nachricht(member: discord.Member):
    channel_id = data.get("channel_blood_in")
    if not channel_id:
        return
    kanal = member.guild.get_channel(int(channel_id))
    if not kanal:
        return
    try:
        await kanal.send(f"🩸 Willkommen {member.mention} auf dem Server!")
    except Exception as e:
        print(f"Fehler beim Senden der Welcome-Nachricht: {e}")

async def sende_leave_nachricht(member: discord.Member):
    channel_id = data.get("channel_blood_out")
    if not channel_id:
        return
    kanal = member.guild.get_channel(int(channel_id))
    if not kanal:
        return
    try:
        await kanal.send(f"🩸 {member.mention} hat den Server verlassen.")
    except Exception as e:
        print(f"Fehler beim Senden der Leave-Nachricht: {e}")

# ─── TASKS ────────────────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def check_zeit():
    now = datetime.now(TIMEZONE)
    h, m = now.hour, now.minute
    heutiger_wochentag  = now.weekday()
    morgiger_wochentag  = (now + timedelta(days=1)).weekday()

    entfernte = await abgelaufene_abmeldungen_aufraeumen()
    if entfernte:
        for guild in bot.guilds:
            if not data.get("eingefroren"):
                await update_nachricht(guild)
            await update_abmeldung_liste(guild)
        print(f"🧹 {len(entfernte)} abgelaufene Abmeldung(en) automatisch entfernt.")

    await alte_aufstellungen_aufraeumen()

    tage_config = data.get("aufstellung_tage_config", {})

    if h == 23 and m == 59:
        morgen_eintrag = tage_config.get(str(morgiger_wochentag), {})
        if morgen_eintrag.get("aktiv"):
            for guild in bot.guilds:
                await neue_abstimmung_posten(guild)
            await asyncio.sleep(61)

    heute_eintrag = tage_config.get(str(heutiger_wochentag), {})
    if heute_eintrag.get("aktiv") and not data.get("eingefroren", False):
        try:
            einfrier_h, einfrier_m = map(int, heute_eintrag.get("uhrzeit", "21:00").split(":"))
        except Exception:
            einfrier_h, einfrier_m = 21, 0
        if h == einfrier_h and m == einfrier_m:
            for guild in bot.guilds:
                await abstimmung_einfrieren(guild)
            await asyncio.sleep(61)

    await check_probewoche_erinnerungen()

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────

@tree.command(name="set_leitung", description="Setzt die Leitungs-Rolle (darf alle Admin-Befehle wie ein Administrator benutzen)")
@app_commands.describe(rolle="Die Rolle, die als Leitung gelten soll")
@app_commands.checks.has_permissions(administrator=True)
async def set_leitung(interaction: discord.Interaction, rolle: discord.Role):
    data["leitung_rolle_id"] = str(rolle.id)
    save_data(data)
    await interaction.response.send_message(
        f"✅ Leitungs-Rolle gesetzt: **{rolle.name}**\nMitglieder dieser Rolle können ab jetzt alle Setup-Befehle nutzen.",
        ephemeral=True
    )

@tree.command(name="setrolle", description="Setzt die Rolle die am Meet Up teilnimmt")
@app_commands.describe(rolle="Die Rolle die gepingt und abgestimmt werden soll")
@app_commands.check(ist_admin_oder_leitung)
async def setrolle(interaction: discord.Interaction, rolle: discord.Role):
    data["rolle_id"] = str(rolle.id)
    save_data(data)
    await interaction.response.send_message(
        f"✅ Rolle **{rolle.name}** wurde gesetzt.\n"
        f"Diese Rolle wird bei jeder Abstimmung gepingt.",
        ephemeral=True
    )

@tree.command(name="set_verifizierungsrolle", description="Legt fest, welche Rolle nach der Verifizierung für einen bestimmten Zweck vergeben wird")
@app_commands.describe(name="Für welchen Zweck ist diese Rolle?", rolle="Die zu vergebende Rolle")
@app_commands.choices(name=[
    app_commands.Choice(name=n, value=n) for n in VERIFIZIERUNGS_ROLLEN_NAMEN
])
@app_commands.check(ist_admin_oder_leitung)
async def set_verifizierungsrolle(interaction: discord.Interaction, name: app_commands.Choice[str], rolle: discord.Role):
    rollen_config = data.setdefault("rollen_nach_verifizierung", {})
    rollen_config[name.value] = str(rolle.id)
    save_data(data)
    await interaction.response.send_message(
        f"✅ **{name.value}** wird nach der Verifizierung ab jetzt als Rolle **{rolle.name}** vergeben.",
        ephemeral=True
    )

@tree.command(name="aufstellungstag", description="Aktiviert/deaktiviert einen Wochentag für das Meet Up und legt seine Uhrzeit fest")
@app_commands.describe(
    tag="Wochentag",
    aktiv="Soll an diesem Tag ein Meet Up sein?",
    uhrzeit="Uhrzeit im Format HH:MM (z.B. 19:30) – optional, wenn nur aktiv/inaktiv geändert wird"
)
@app_commands.choices(tag=[
    app_commands.Choice(name=n, value=str(i)) for i, n in enumerate(WOCHENTAGE_NAMEN)
])
@app_commands.check(ist_admin_oder_leitung)
async def aufstellungstag(interaction: discord.Interaction, tag: app_commands.Choice[str], aktiv: bool, uhrzeit: str = None):
    tag_key = tag.value
    config  = data.setdefault("aufstellung_tage_config", {})
    eintrag = config.get(tag_key, {"aktiv": False, "uhrzeit": "20:00"})
    eintrag["aktiv"] = aktiv

    if uhrzeit:
        uhrzeit = uhrzeit.strip()
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", uhrzeit):
            await interaction.response.send_message(
                "❌ Ungültiges Uhrzeit-Format. Bitte HH:MM verwenden, z.B. 19:30", ephemeral=True
            )
            return
        eintrag["uhrzeit"] = uhrzeit

    config[tag_key] = eintrag
    data["aufstellung_tage_config"] = config
    save_data(data)

    status = "**aktiv**" if aktiv else "**deaktiviert**"
    await interaction.response.send_message(
        f"✅ {WOCHENTAGE_NAMEN[int(tag_key)]}: {status}, Uhrzeit **{eintrag['uhrzeit']} Uhr**",
        ephemeral=True
    )

@tree.command(name="aufstellungstage", description="Zeigt die Konfiguration aller Wochentage")
@app_commands.check(ist_admin_oder_leitung)
async def aufstellungstage_uebersicht(interaction: discord.Interaction):
    config = data.get("aufstellung_tage_config", {})
    zeilen = []
    for i, name in enumerate(WOCHENTAGE_NAMEN):
        eintrag = config.get(str(i), {"aktiv": False, "uhrzeit": "20:00"})
        symbol  = "✅" if eintrag.get("aktiv") else "❌"
        zeilen.append(f"{symbol} **{name}** — {eintrag.get('uhrzeit', '20:00')} Uhr")
    await interaction.response.send_message("\n".join(zeilen), ephemeral=True)

@tree.command(name="set_aufstellung", description="Setzt den Channel für die Meet Up-Abstimmung")
@app_commands.describe(channel="Der Channel wo die Abstimmung gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_aufstellung(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_aufstellung"] = channel.id
    save_data(data)
    await interaction.response.send_message(
        f"✅ Meet Up-Channel gesetzt: {channel.mention}", ephemeral=True
    )

@tree.command(name="set_archiv", description="Setzt den Channel für das Meet Up-Archiv")
@app_commands.describe(channel="Der Channel wo die archivierten Abstimmungen landen")
@app_commands.check(ist_admin_oder_leitung)
async def set_archiv(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_archiv"] = channel.id
    save_data(data)
    await interaction.response.send_message(
        f"✅ Archiv-Channel gesetzt: {channel.mention}", ephemeral=True
    )

@tree.command(name="set_abmeldung", description="Setzt den Channel für Abmeldungen")
@app_commands.describe(channel="Der Channel wo Abmeldungen gepostet werden")
@app_commands.check(ist_admin_oder_leitung)
async def set_abmeldung(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_abmeldung"] = channel.id
    save_data(data)
    await interaction.response.send_message(
        f"✅ Abmeldungs-Channel gesetzt: {channel.mention}", ephemeral=True
    )

@tree.command(name="set_abmeldung_liste", description="Setzt den Channel für die Abmeldungs-Übersicht (Live-Liste)")
@app_commands.describe(channel="Der Channel wo die aktuelle Übersicht aller Abmeldungen als Liste gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_abmeldung_liste(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_abmeldung_liste"] = channel.id
    data["abmeldung_liste_nachricht_id"] = None
    save_data(data)
    await interaction.response.send_message(
        f"✅ Abmeldungs-Übersicht-Channel gesetzt: {channel.mention}", ephemeral=True
    )
    await update_abmeldung_liste(interaction.guild)

@tree.command(name="set_abmeldung_button", description="Setzt den Channel für den Abmeldung-Button")
@app_commands.describe(channel="Der Channel wo der 'Abmeldung' Button gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_abmeldung_button(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_abmeldung_button"] = channel.id
    data["abmeldung_button_nachricht_id"] = None
    save_data(data)
    await interaction.response.send_message(
        f"✅ Abmeldung-Button-Channel gesetzt: {channel.mention}", ephemeral=True
    )
    await abmeldung_button_posten_intern(interaction.guild)

@tree.command(name="abmeldung_button_posten", description="Postet oder aktualisiert die Abmeldung-Button-Nachricht")
@app_commands.check(ist_admin_oder_leitung)
async def abmeldung_button_posten(interaction: discord.Interaction):
    if not data.get("channel_abmeldung_button"):
        await interaction.response.send_message(
            "❌ Kein Channel gesetzt!\nBitte zuerst **/set_abmeldung_button #channel** benutzen.",
            ephemeral=True
        )
        return
    await abmeldung_button_posten_intern(interaction.guild)
    await interaction.response.send_message("✅ Abmeldung-Button-Nachricht gepostet/aktualisiert.", ephemeral=True)

@tree.command(name="set_verifizierung_channel", description="Setzt den Channel für die Verifizierungs-Nachricht (Button)")
@app_commands.describe(channel="Der Channel wo neue Mitglieder sich verifizieren")
@app_commands.check(ist_admin_oder_leitung)
async def set_verifizierung_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_verifizierung"] = channel.id
    data["verifizierung_nachricht_id"] = None
    save_data(data)
    await interaction.response.send_message(f"✅ Verifizierungs-Channel gesetzt: {channel.mention}", ephemeral=True)
    await verifizierung_posten_intern(interaction.guild)

@tree.command(name="verifizierung_posten", description="Postet oder aktualisiert die Verifizierungs-Nachricht")
@app_commands.check(ist_admin_oder_leitung)
async def verifizierung_posten(interaction: discord.Interaction):
    if not data.get("channel_verifizierung"):
        await interaction.response.send_message(
            "❌ Kein Channel gesetzt!\nBitte zuerst **/set_verifizierung_channel #channel** benutzen.",
            ephemeral=True
        )
        return
    await verifizierung_posten_intern(interaction.guild)
    await interaction.response.send_message("✅ Verifizierungs-Nachricht gepostet/aktualisiert.", ephemeral=True)

@tree.command(name="set_verifizierung_log", description="Setzt den Channel für das Verifizierungs-Log")
@app_commands.describe(channel="Der Channel wo jede neue Verifizierung protokolliert wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_verifizierung_log(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_verifizierung_log"] = channel.id
    save_data(data)
    await interaction.response.send_message(f"✅ Verifizierungs-Log-Channel gesetzt: {channel.mention}", ephemeral=True)

@tree.command(name="probezeit_beenden", description="Beendet die Probezeit eines Mitglieds vorzeitig")
@app_commands.describe(mitglied="Das Mitglied dessen Probezeit vorzeitig beendet wird")
@app_commands.check(ist_admin_oder_leitung)
async def probezeit_beenden(interaction: discord.Interaction, mitglied: discord.Member):
    probezeit_rolle_id = data.get("rollen_nach_verifizierung", {}).get("Probezeit")
    entfernt = False
    if probezeit_rolle_id:
        rolle = interaction.guild.get_role(int(probezeit_rolle_id))
        if rolle and rolle in mitglied.roles:
            try:
                await mitglied.remove_roles(rolle)
                entfernt = True
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ Ich habe keine Berechtigung, die Probezeit-Rolle zu entfernen.", ephemeral=True
                )
                return

    uid = str(mitglied.id)
    verifizierungen = data.setdefault("verifizierungen", {})
    if uid in verifizierungen:
        verifizierungen[uid]["erinnert"] = True
        save_data(data)

    if entfernt:
        await interaction.response.send_message(
            f"✅ Probezeit von **{mitglied.display_name}** vorzeitig beendet (Rolle entfernt).", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ **{mitglied.display_name}** hatte keine Probezeit-Rolle mehr, Eintrag trotzdem als beendet markiert.",
            ephemeral=True
        )

@tree.command(name="set_probewoche_channel", description="Setzt den Channel für die automatische Probewoche-Erinnerung nach 7 Tagen")
@app_commands.describe(channel="Der Channel wo die Erinnerung gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_probewoche_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_probewoche_erinnerung"] = channel.id
    save_data(data)
    await interaction.response.send_message(f"✅ Probewoche-Erinnerungs-Channel gesetzt: {channel.mention}", ephemeral=True)

@tree.command(name="set_blood_in", description="Setzt den Channel für die Willkommens-Nachricht (Join)")
@app_commands.describe(channel="Der Channel wo die Willkommens-Nachricht gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_blood_in(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_blood_in"] = channel.id
    save_data(data)
    await interaction.response.send_message(f"✅ Blood-In-Channel (Willkommen) gesetzt: {channel.mention}", ephemeral=True)

@tree.command(name="set_blood_out", description="Setzt den Channel für die Abschieds-Nachricht (Leave)")
@app_commands.describe(channel="Der Channel wo die Abschieds-Nachricht gepostet wird")
@app_commands.check(ist_admin_oder_leitung)
async def set_blood_out(interaction: discord.Interaction, channel: discord.TextChannel):
    data["channel_blood_out"] = channel.id
    save_data(data)
    await interaction.response.send_message(f"✅ Blood-Out-Channel (Abschied) gesetzt: {channel.mention}", ephemeral=True)

@tree.command(name="channels", description="Zeigt alle aktuell gesetzten Channels und Rollen")
@app_commands.check(ist_admin_oder_leitung)
async def channels_info(interaction: discord.Interaction):
    auf    = interaction.guild.get_channel(int(data["channel_aufstellung"]))       if data.get("channel_aufstellung")       else None
    arch   = interaction.guild.get_channel(int(data["channel_archiv"]))            if data.get("channel_archiv")            else None
    abm    = interaction.guild.get_channel(int(data["channel_abmeldung"]))         if data.get("channel_abmeldung")         else None
    liste  = interaction.guild.get_channel(int(data["channel_abmeldung_liste"]))   if data.get("channel_abmeldung_liste")   else None
    button = interaction.guild.get_channel(int(data["channel_abmeldung_button"]))  if data.get("channel_abmeldung_button")  else None
    verif  = interaction.guild.get_channel(int(data["channel_verifizierung"]))     if data.get("channel_verifizierung")     else None
    vlog   = interaction.guild.get_channel(int(data["channel_verifizierung_log"])) if data.get("channel_verifizierung_log") else None
    probe_ch = interaction.guild.get_channel(int(data["channel_probewoche_erinnerung"])) if data.get("channel_probewoche_erinnerung") else None
    blood_in  = interaction.guild.get_channel(int(data["channel_blood_in"]))  if data.get("channel_blood_in")  else None
    blood_out = interaction.guild.get_channel(int(data["channel_blood_out"])) if data.get("channel_blood_out") else None

    leitung_rolle_id = data.get("leitung_rolle_id")
    leitung_rolle = interaction.guild.get_role(int(leitung_rolle_id)) if leitung_rolle_id else None

    rolle_id = data.get("rolle_id")
    rolle = interaction.guild.get_role(int(rolle_id)) if rolle_id else None

    rollen_config = data.get("rollen_nach_verifizierung", {})
    verif_rollen_status = []
    for name in VERIFIZIERUNGS_ROLLEN_NAMEN:
        rid = rollen_config.get(name)
        r = interaction.guild.get_role(int(rid)) if rid else None
        verif_rollen_status.append(f"{name}: {r.mention if r else '❌ nicht gesetzt'}")

    config = data.get("aufstellung_tage_config", {})
    aktive_tage = [WOCHENTAGE_NAMEN[i] for i in range(7) if config.get(str(i), {}).get("aktiv")]
    tage_text = ", ".join(aktive_tage) if aktive_tage else "Keine (nutze /aufstellungstag)"

    await interaction.response.send_message(
        f"**Aktuelle Einstellungen:**\n\n"
        f"Leitungs-Rolle:        {leitung_rolle.mention if leitung_rolle else '❌ Nicht gesetzt – /set_leitung benutzen'}\n"
        f"Rolle (Meet Up):       {rolle.mention        if rolle        else '❌ Nicht gesetzt – /setrolle benutzen'}\n"
        f"Meet Up:               {auf.mention          if auf          else '❌ Nicht gesetzt – /set_aufstellung benutzen'}\n"
        f"Archiv:                {arch.mention         if arch         else '❌ Nicht gesetzt – /set_archiv benutzen'}\n"
        f"Abmeldung (Log):       {abm.mention          if abm          else '❌ Nicht gesetzt – /set_abmeldung benutzen'}\n"
        f"Abmeldungs-Liste:      {liste.mention        if liste        else '❌ Nicht gesetzt – /set_abmeldung_liste benutzen'}\n"
        f"Abmeldung-Button:      {button.mention       if button       else '❌ Nicht gesetzt – /set_abmeldung_button benutzen'}\n\n"
        f"Aktive Meet Up-Tage: **{tage_text}**\n"
        f"(Details: /aufstellungstage)\n\n"
        f"Verifizierung-Channel: {verif.mention        if verif        else '❌ Nicht gesetzt – /set_verifizierung_channel benutzen'}\n"
        f"Verifizierung-Log:     {vlog.mention         if vlog         else '❌ Nicht gesetzt – /set_verifizierung_log benutzen'}\n"
        f"Rollen nach Verify:    {' | '.join(verif_rollen_status)}\n"
        f"(Setzen: /set_verifizierungsrolle)\n"
        f"Probewoche-Erinnerung: {probe_ch.mention     if probe_ch     else '❌ Nicht gesetzt – /set_probewoche_channel benutzen'}\n\n"
        f"Blood In (Willkommen): {blood_in.mention     if blood_in     else '❌ Nicht gesetzt – /set_blood_in benutzen'}\n"
        f"Blood Out (Abschied):  {blood_out.mention    if blood_out    else '❌ Nicht gesetzt – /set_blood_out benutzen'}",
        ephemeral=True
    )

@tree.command(name="abstimmung", description="Postet manuell eine neue Meet Up-Abstimmung")
@app_commands.describe(datum="Für welchen Tag gilt das Meet Up? (Standard: Heute)")
@app_commands.choices(datum=[
    app_commands.Choice(name="Heute", value="heute"),
    app_commands.Choice(name="Morgen", value="morgen"),
])
@app_commands.check(ist_admin_oder_leitung)
async def abstimmung_manuell(interaction: discord.Interaction, datum: app_commands.Choice[str] = None):
    if not data.get("channel_aufstellung"):
        await interaction.response.send_message(
            "❌ Kein Meet Up-Channel gesetzt!\nBitte zuerst **/set_aufstellung #channel** benutzen.",
            ephemeral=True
        )
        return
    verwende_heute = (datum is None) or (datum.value == "heute")
    await interaction.response.send_message("Erstelle neue Abstimmung...", ephemeral=True)
    await neue_abstimmung_posten(interaction.guild, verwende_heute=verwende_heute)
    await interaction.edit_original_response(content="✅ Neue Abstimmung wurde gepostet!")

@tree.command(name="status", description="Zeigt den aktuellen Abstimmungsstand")
@app_commands.check(ist_admin_oder_leitung)
async def status(interaction: discord.Interaction):
    mitglieder = await get_rolle_mitglieder(interaction.guild)
    datum      = data.get("aktuelles_datum", get_morgen_datum())
    embed      = build_embed(datum, mitglieder, data.get("eingefroren", False))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="abmelden", description="Melde dich vom Meet Up ab")
@app_commands.describe(
    von="Von wann? (TT.MM.JJJJ, z.B. 14.07.2026)",
    bis="Bis wann? (TT.MM.JJJJ, z.B. 16.07.2026)",
    grund="Grund (intern, nicht öffentlich sichtbar)"
)
async def abmelden(interaction: discord.Interaction, von: str, bis: str, grund: str):
    rolle_id = data.get("rolle_id")
    if rolle_id:
        rolle = interaction.guild.get_role(int(rolle_id))
        if rolle and rolle not in interaction.user.roles:
            await interaction.response.send_message(
                "Du hast keine Berechtigung zur Abmeldung.", ephemeral=True
            )
            return

    von_datum = parse_datum(von)
    bis_datum = parse_datum(bis)
    if not von_datum or not bis_datum:
        await interaction.response.send_message(
            "❌ Ungültiges Datumsformat. Bitte **TT.MM.JJJJ** verwenden, z.B. `14.07.2026`.", ephemeral=True
        )
        return
    if bis_datum < von_datum:
        await interaction.response.send_message(
            "❌ Das Enddatum darf nicht vor dem Startdatum liegen.", ephemeral=True
        )
        return
    von, bis = von_datum.strftime("%d.%m.%Y"), bis_datum.strftime("%d.%m.%Y")

    uid = str(interaction.user.id)
    data["abmeldungen"][uid] = {"von": von, "bis": bis, "grund": grund, "typ": "kurzzeit"}
    save_data(data)

    if not data.get("eingefroren"):
        await update_nachricht(interaction.guild)
    await update_abmeldung_liste(interaction.guild)

    aktiv_hinweis = "" if ist_abmeldung_aktiv(data["abmeldungen"][uid]) else \
        "\nℹ️ Dein Zeitraum beginnt erst später – bis dahin wirst du weiterhin normal im Meet Up geführt und kannst abstimmen."
    await interaction.response.send_message(
        f"✅ Abmeldung eingetragen!\n"
        f"Von: **{von}**\n"
        f"Bis: **{bis}**{aktiv_hinweis}",
        ephemeral=True
    )

    if data.get("channel_abmeldung"):
        abm_kanal = interaction.guild.get_channel(int(data["channel_abmeldung"]))
        if abm_kanal:
            embed_abm = discord.Embed(title="Neue Abmeldung", color=EMBED_COLOR)
            embed_abm.add_field(name="Mitglied", value=interaction.user.mention, inline=True)
            embed_abm.add_field(name="Von",      value=von,                      inline=True)
            embed_abm.add_field(name="Bis",      value=bis,                      inline=True)
            embed_abm.add_field(name="Grund",    value=grund,                    inline=False)
            embed_abm.set_footer(text="Blue End")
            embed_abm.timestamp = datetime.now(TIMEZONE)
            await abm_kanal.send(embed=embed_abm)

@tree.command(name="abmeldung_langzeit", description="Trägt eine Langzeit-Abmeldung ein (Zeitraum länger als eine Woche)")
@app_commands.describe(
    von="Von wann? (TT.MM.JJJJ, z.B. 14.07.2026)",
    bis="Bis wann? (TT.MM.JJJJ, z.B. 25.08.2026)",
    grund="Grund der Langzeit-Abmeldung"
)
async def abmeldung_langzeit(interaction: discord.Interaction, von: str, bis: str, grund: str):
    rolle_id = data.get("rolle_id")
    if rolle_id:
        rolle = interaction.guild.get_role(int(rolle_id))
        if rolle and rolle not in interaction.user.roles:
            await interaction.response.send_message(
                "Du hast keine Berechtigung zur Abmeldung.", ephemeral=True
            )
            return

    von_datum = parse_datum(von)
    bis_datum = parse_datum(bis)
    if not von_datum or not bis_datum:
        await interaction.response.send_message(
            "❌ Ungültiges Datumsformat. Bitte **TT.MM.JJJJ** verwenden, z.B. `14.07.2026`.", ephemeral=True
        )
        return
    if bis_datum < von_datum:
        await interaction.response.send_message(
            "❌ Das Enddatum darf nicht vor dem Startdatum liegen.", ephemeral=True
        )
        return
    von, bis = von_datum.strftime("%d.%m.%Y"), bis_datum.strftime("%d.%m.%Y")

    uid = str(interaction.user.id)
    data["abmeldungen"][uid] = {"von": von, "bis": bis, "grund": grund, "typ": "langzeit"}
    save_data(data)

    if not data.get("eingefroren"):
        await update_nachricht(interaction.guild)
    await update_abmeldung_liste(interaction.guild)

    aktiv_hinweis = "" if ist_abmeldung_aktiv(data["abmeldungen"][uid]) else \
        "\nℹ️ Dein Zeitraum beginnt erst später – bis dahin wirst du weiterhin normal im Meet Up geführt und kannst abstimmen."
    await interaction.response.send_message(
        f"✅ Langzeit-Abmeldung eingetragen!\n"
        f"Von: **{von}**\n"
        f"Bis: **{bis}**{aktiv_hinweis}",
        ephemeral=True
    )

    if data.get("channel_abmeldung"):
        abm_kanal = interaction.guild.get_channel(int(data["channel_abmeldung"]))
        if abm_kanal:
            embed_abm = discord.Embed(title="Neue Langzeit-Abmeldung", color=EMBED_COLOR)
            embed_abm.add_field(name="Mitglied", value=interaction.user.mention, inline=True)
            embed_abm.add_field(name="Von",      value=von,                      inline=True)
            embed_abm.add_field(name="Bis",      value=bis,                      inline=True)
            embed_abm.add_field(name="Grund",    value=grund,                    inline=False)
            embed_abm.set_footer(text="Blue End")
            embed_abm.timestamp = datetime.now(TIMEZONE)
            await abm_kanal.send(embed=embed_abm)

@tree.command(name="abmeldung_loeschen", description="Entfernt die Abmeldung eines Mitglieds")
@app_commands.describe(mitglied="Das Mitglied dessen Abmeldung entfernt werden soll")
@app_commands.check(ist_admin_oder_leitung)
async def abmeldung_loeschen(interaction: discord.Interaction, mitglied: discord.Member):
    uid = str(mitglied.id)
    if uid in data["abmeldungen"]:
        del data["abmeldungen"][uid]
        save_data(data)
        await update_nachricht(interaction.guild)
        await update_abmeldung_liste(interaction.guild)
        await interaction.response.send_message(
            f"✅ Abmeldung von **{mitglied.display_name}** entfernt.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ **{mitglied.display_name}** hat keine aktive Abmeldung.", ephemeral=True
        )

# ─── BOT EVENTS ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild_obj)
            synced = await tree.sync(guild=guild_obj)
            print(f"✅ {len(synced)} Commands SOFORT auf Guild {GUILD_ID} gesynct: {[c.name for c in synced]}")
        else:
            print("⚠️ Keine GUILD_ID gesetzt — sync läuft global (kann bis zu 1h dauern).")

        synced_global = await tree.sync()
        print(f"✅ {len(synced_global)} Commands global gesynct: {[c.name for c in synced_global]}")
    except Exception as e:
        print(f"❌ FEHLER beim Sync: {e}")

    bot.add_view(AufstellungView())
    bot.add_view(AbmeldungButtonView())
    bot.add_view(VerifizierungButtonView())

    # ── AUTO-POST FEHLENDER NACHRICHTEN ─────────────────────────────────────
    # Da die Channel-/Rollen-IDs jetzt beim Start automatisch vorausgefüllt
    # werden, postet der Bot hier direkt die Verifizierungs- und Abmeldung-
    # Button-Nachricht sowie die Abmeldungs-Übersicht, falls diese noch
    # nicht existieren.
    for guild in bot.guilds:
        try:
            if data.get("channel_verifizierung") and not data.get("verifizierung_nachricht_id"):
                await verifizierung_posten_intern(guild)
                print("✅ Verifizierungs-Nachricht nachträglich gepostet.")
            if data.get("channel_abmeldung_button") and not data.get("abmeldung_button_nachricht_id"):
                await abmeldung_button_posten_intern(guild)
                print("✅ Abmeldung-Button-Nachricht nachträglich gepostet.")
            if data.get("channel_abmeldung_liste"):
                await update_abmeldung_liste(guild)
                print("✅ Abmeldungs-Übersicht nachträglich gepostet/aktualisiert.")
        except Exception as e:
            print(f"❌ Fehler beim Auto-Posten fehlender Nachrichten: {e}")

    check_zeit.start()
    print("Tasks gestartet. Bot ist bereit!")

@bot.event
async def on_member_join(member: discord.Member):
    await sende_welcome_nachricht(member)

@bot.event
async def on_member_remove(member: discord.Member):
    await sende_leave_nachricht(member)

@bot.event
async def on_message(message: discord.Message):
    # Eigene Nachrichten des Bots ignorieren, damit er sich nicht selbst triggert.
    if message.author.bot:
        await bot.process_commands(message)
        return

    await bot.process_commands(message)

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "Du hast keine Berechtigung für diesen Befehl.", ephemeral=True
        )
    else:
        print(f"Command Error: {error}")
        try:
            await interaction.response.send_message("Ein Fehler ist aufgetreten.", ephemeral=True)
        except:
            pass

# ─── START ────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
