# xdecahx: Tam Entegre Discord Botu
# Özellikler: Join sistemi, map ban, ready, ceza, puan, MVP, /ban, /profile, /setup

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select
from discord import app_commands
import asyncio
import random
import datetime
import pytz
import json
import os

reroll_requests = {}  # {kanal_id: [kullanıcı_id]}
reroll_done = set()   # reroll yapılmış kanallar
map_data = {}         # {kanal_id: secilen_harita}

RANKLAR = {
    "🥉 Bronze": (100, 499),
    "🥈 Silver": (500, 999),
    "🥇 Gold": (1000, 1399),
    "💎 Diamond": (1400, 10000)
}

RANK_DATA_FILE = "rank_data.json"

def load_rank_data():
    if os.path.exists(RANK_DATA_FILE):
        with open(RANK_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_rank_data(data):
    with open(RANK_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def update_user_point(user_id, new_point):
    rank_data = load_rank_data()
    safe_point = max(100, new_point)  # Puan asla 100'ün altına düşmesin
    if str(user_id) in rank_data:
        rank_data[str(user_id)]["point"] = safe_point
    else:
        rank_data[str(user_id)] = {"rank": "", "point": safe_point}
    save_rank_data(rank_data)

async def assign_rank_role(member, puan):
    guild = member.guild
    matched_rank = None

    # ✅ Doğru rank'ı bul
    for rank_name, (min_point, max_point) in RANKLAR.items():
        if min_point <= puan <= max_point:
            matched_rank = rank_name
            break

    if matched_rank is None:
        return  # Eşleşen rank yoksa çık

    # ⛔ Zaten doğru rank rolüne sahipse hiçbir şey yapma
    for rol in member.roles:
        if rol.name.lower() == matched_rank.lower():
            return

    # ✅ Mevcut rank rollerini sil
    for rol in member.roles:
        for rank in RANKLAR.keys():
            if rol.name.lower() == rank.lower():
                try:
                    await member.remove_roles(rol)
                except discord.Forbidden:
                    print(f"❌ Rol silinemedi: {rol.name}")
                except discord.HTTPException:
                    print(f"❌ Rol silme hatası: {rol.name}")

    # ✅ Rolü bul ya da oluştur
    role = discord.utils.get(guild.roles, name=matched_rank)
    if role is None:
        try:
            role = await guild.create_role(name=matched_rank)
        except discord.Forbidden:
            print(f"❌ Bot '{matched_rank}' rolünü oluşturamıyor. Yetkileri kontrol et.")
            return
        except discord.HTTPException:
            print(f"❌ '{matched_rank}' rolü oluşturulurken hata oluştu.")
            return

    # ✅ Yeni rank rolünü ata
    try:
        await member.add_roles(role)
    except discord.Forbidden:
        print(f"❌ Bot '{role.name}' rolünü {member.display_name} adlı kullanıcıya veremiyor.")
        return
    except discord.HTTPException:
        print(f"❌ '{role.name}' rolü eklenirken hata oluştu.")
        return

    # ✅ Rank verisini JSON dosyasına yaz
    update_user_point(member.id, puan)

# Diğer global değişkenler
maç_kanalları = {}  # Kanal adı → (players, alpha_team, beta_team)
nickname_kullananlar = set()  # Kullanıcı ID'leri, sadece 1 kez isim değiştirebilir

from discord.ext import tasks  # Eğer dosyanın en üstünde yoksa eklemeyi unutma

@tasks.loop(minutes=0.1)
async def rank_auto_loop():
    for guild in bot.guilds:
        rank_data = load_rank_data()
        değişiklik_yapıldı = False  # Dosyayı boşuna kaydetmemek için

        # rank_data'daki her kullanıcıyı kontrol et
        for user_id in list(rank_data.keys()):
            member = guild.get_member(int(user_id))
            if not member:
                # Sunucudan çıkmış, verisini sil
                del rank_data[user_id]
                değişiklik_yapıldı = True
                continue

            await assign_rank_role(member, rank_data[user_id].get("point", 0))

        if değişiklik_yapıldı:
            save_rank_data(rank_data)



TOKEN = "MTM3NDQ5MDAzNTg1NjA4NDk5Mg.GC-rNj.unWWBWFQNuPJHJea7oTmmi44J-ou0uXN8Gr-eY"  # ← Bot token'ını buraya ekle

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

def extract_point_from_name(name):
    if name.endswith("p"):
        try:
            point_part = name.split("-")[-1].strip()
            return int(point_part[:-1])
        except:
            return 100
    return 100

MAP_LIST = [
    "<:st:1375807369883291679> STATION - 2",
    "<:hh:1375806530624159775> HIGHWAY",
    "<:os:1375806992261840906> OLDCSHOOL",
    "<:tn:1375805831118852127> TUNNEL",
    "<:jl:1375805552252420160> JUNGLE",
    "<:n3:1375806048807555206> NEDEN - 3",
    "<:tp:1375814466607779930> TEMPLE - M",
    "<:zg:1375806764943016116> ZIGGURAT",
    "<:cs:1375807162558844999> COLOSEUM"
]


JOIN_CHANNELS = {
    "3v3-general": {"max_players": 6},
    "2v2-general": {"max_players": 4}
}

user_queues = {k: [] for k in JOIN_CHANNELS}
join_messages = {}
user_data = {}  # kullanıcı_id: {"puan": int, "rank": str}
cezali_oyuncular = {}  # kullanıcı_id: bitiş_zamanı (datetime objesi)
active_games = []

class JoinLeaveView(View):
    def __init__(self, channel_key):
        super().__init__(timeout=None)
        self.channel_key = channel_key
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        count = len(user_queues[self.channel_key])
        max_players = JOIN_CHANNELS[self.channel_key]["max_players"]

        join_button = Button(label="Join", style=discord.ButtonStyle.success)
        leave_button = Button(label="Leave", style=discord.ButtonStyle.danger)
        count_button = Button(label=f"{count}/{max_players}", style=discord.ButtonStyle.secondary, disabled=True)

        async def on_join(interaction):
            user = interaction.user
            if user.id in cezali_oyuncular and cezali_oyuncular[user.id] > datetime.datetime.utcnow():
                await interaction.response.send_message("⛔ Cezalısın. Katılamazsın.", ephemeral=True)
                return
            if user not in user_queues[self.channel_key]:
                user_queues[self.channel_key].append(user)
                self.update_buttons()
                await interaction.response.edit_message(view=self)
                if len(user_queues[self.channel_key]) == max_players:
                    await start_match(interaction.guild, self.channel_key)
            else:
                await interaction.response.send_message("✅ Zaten listedesin.", ephemeral=True)

        async def on_leave(interaction):
            user = interaction.user
            if user in user_queues[self.channel_key]:
                user_queues[self.channel_key].remove(user)
                self.update_buttons()
                await interaction.response.edit_message(view=self)
            else:
                await interaction.response.send_message("❌ Listede yoksun.", ephemeral=True)

        join_button.callback = on_join
        leave_button.callback = on_leave
        self.add_item(join_button)
        self.add_item(leave_button)
        self.add_item(count_button)

    def update_and_return(self):
        self.update_buttons()
        return self
class NicknameModal(discord.ui.Modal, title="🎮 Oyun İçi İsmini Belirle"):
    nickname = discord.ui.TextInput(label="İsminizi girin", placeholder="Ahmet", max_length=20)

    def __init__(self, user, interaction):
        super().__init__()
        self.user = user
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if self.user.id in nickname_kullananlar:
            await interaction.response.send_message("❌ İsmini zaten değiştirdin.", ephemeral=True)
            return

        base_nick = self.nickname.value.strip()
        if not base_nick:
            await interaction.response.send_message("❌ Geçerli bir isim girmelisin.", ephemeral=True)
            return

        user_data.setdefault(self.user.id, {"puan": 100})
        puan = user_data[self.user.id]["puan"]
        final_nick = f"{base_nick} - {puan}p"

        try:
            await self.user.edit(nick=final_nick)
            nickname_kullananlar.add(self.user.id)
            await interaction.response.send_message(f"✅ İsmin başarıyla `{final_nick}` olarak ayarlandı.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Botun ismini değiştirme yetkisi yok.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Hata: {e}", ephemeral=True)

class NicknameView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 Nickname Belirle", style=discord.ButtonStyle.primary, custom_id="set_nick")
    async def set_nick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.name != "oyun-ici-nickname":
            await interaction.response.send_message("❌ Bu buton sadece `#oyun-ici-nickname` kanalında kullanılabilir.", ephemeral=True)
            return

        if interaction.user.id in nickname_kullananlar:
            await interaction.response.send_message("❌ İsmini zaten değiştirdin.", ephemeral=True)
            return

        await interaction.response.send_modal(NicknameModal(interaction.user, interaction))
        
async def start_match(guild, channel_key):
    players = user_queues[channel_key][:]
    user_queues[channel_key] = []
    category = discord.utils.get(guild.categories, name="Match Making")
    match_number = len([ch for ch in guild.text_channels if ch.name.startswith(f"{channel_key}-match")]) + 1
    channel = await guild.create_text_channel(f"{channel_key}-match-{match_number}", category=category)

    await channel.send("🎮 Maç Başlıyor! Oyuncular: " + ", ".join(p.mention for p in players))

    if len(players) == 6:
        await process_3v3_match(channel, players)
    else:
        await process_2v2_match(channel, players)
async def process_3v3_match(channel, players):
    alpha_captain = random.choice(players)
    beta_captain = random.choice([p for p in players if p != alpha_captain])
    remaining_players = [p for p in players if p not in (alpha_captain, beta_captain)]

    alpha_team = [alpha_captain]
    beta_team = [beta_captain]

    await channel.send(f"👑 **Takım kaptanları belirlendi!**\n"
                       f"Alpha Kaptanı: {alpha_captain.mention}\n"
                       f"Beta Kaptanı: {beta_captain.mention}\n\n"
                       f"{alpha_captain.mention}, `=p @kullanıcı` komutuyla 1 oyuncu seç.")

    def check_alpha(m):
        return (
            m.channel == channel and
            m.author == alpha_captain and
            m.content.startswith("=p") and
            len(m.mentions) == 1 and
            m.mentions[0] in remaining_players
        )

    try:
        msg = await bot.wait_for("message", check=check_alpha, timeout=60)
        selected = msg.mentions[0]
        alpha_team.append(selected)
        remaining_players.remove(selected)
    except asyncio.TimeoutError:
        await channel.send("⛔ Alpha kaptanı zamanında seçim yapmadı. Maç iptal edildi.")
        await asyncio.sleep(5)
        await channel.delete()
        return

    await channel.send(f"{beta_captain.mention}, `=p @kullanıcı1 @kullanıcı2` komutuyla 2 oyuncu seç.")

    def check_beta(m):
        return (
            m.channel == channel and
            m.author == beta_captain and
            m.content.startswith("=p") and
            len(m.mentions) == 2 and
            all(p in remaining_players for p in m.mentions)
        )

    try:
        msg = await bot.wait_for("message", check=check_beta, timeout=60)
        selected = msg.mentions
        beta_team.extend(selected)
        for p in selected:
            remaining_players.remove(p)
    except asyncio.TimeoutError:
        await channel.send("⛔ Beta kaptanı zamanında seçim yapmadı. Maç iptal edildi.")
        await asyncio.sleep(5)
        await channel.delete()
        return

    # Son kalan oyuncu Alpha'ya
    alpha_team.append(remaining_players[0])

    await channel.send(f"✅ Takımlar hazır!\n\n"
                       f"**Alpha:** {', '.join(p.mention for p in alpha_team)}\n"
                       f"**Beta:** {', '.join(p.mention for p in beta_team)}")

    maç_kanalları[channel.name] = (players, alpha_team, beta_team)

    # Harita banlama aşamasına geç
    await map_ban(channel, alpha_captain, beta_captain, alpha_team, beta_team)

async def process_2v2_match(channel, players):
    random.shuffle(players)
    alpha_team = players[:2]
    beta_team = players[2:]
    alpha = alpha_team[0]
    beta = beta_team[0]

    await channel.send(f"🔵 **Alpha:** {', '.join(p.mention for p in alpha_team)}\n"
                       f"🔴 **Beta:** {', '.join(p.mention for p in beta_team)}")

    # ✅ Maçı kayıt altına alıyoruz
    maç_kanalları[channel.name] = (players, alpha_team, beta_team)

    await map_ban(channel, alpha, beta, alpha_team, beta_team)

async def map_ban(channel, alpha, beta, alpha_team, beta_team):
    banned = []

    class MapSelect(discord.ui.Select):
        def __init__(self, user, maps):
            super().__init__(placeholder="Banlamak için harita seç", options=[
                discord.SelectOption(label=m) for m in maps
            ])
            self.user = user

        async def callback(self, interaction: discord.Interaction):
            if interaction.user != self.user:
                await interaction.response.send_message("Bu senin sıran değil.", ephemeral=True)
                return
            banned.append(self.values[0])
            await interaction.response.send_message(f"❌ `{self.values[0]}` banlandı.")
            self.view.stop()

    async def ask_ban(user, remaining_maps):
        view = discord.ui.View(timeout=120)
        select = MapSelect(user, remaining_maps)
        view.add_item(select)
        await channel.send(f"{user.mention}, harita banla (2 dakika içinde):", view=view)
        await view.wait()

    # ✅ ask_ban çağrıları burada olmalı
    await ask_ban(alpha, MAP_LIST)
    await ask_ban(beta, [m for m in MAP_LIST if m not in banned])
    
    kalan = [m for m in MAP_LIST if m not in banned]
    selected = random.choice(kalan)
    await channel.send(f"✅ Oynanacak harita: **{selected}**")
    
        # Seçilen haritayı kaydet (reroll için)
    map_data[channel.id] = selected
    reroll_requests[channel.id] = []
    reroll_done.discard(channel.id)

    # Hazır sistemini tetikle
    await ready_check(channel, alpha_team + beta_team, alpha_team, beta_team)

async def ready_check(channel, players, alpha_team, beta_team):
    ready_users = set()

    class ReadyView(View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(Button(label="✅ Hazırım", style=discord.ButtonStyle.success, custom_id="ready"))

        async def interaction_check(self, interaction):
            if interaction.data["custom_id"] == "ready":
                ready_users.add(interaction.user.id)
                await interaction.response.send_message("✅ Hazır oldun!", ephemeral=True)
                return True
            return False

    view = ReadyView()
    await channel.send("🕒 Lütfen 2 dakika içinde hazır olun amk!", view=view)
    await view.wait()

    if len(ready_users) < len(players):
        not_ready = [p for p in players if p.id not in ready_users]
        for p in not_ready:
            user_data.setdefault(p.id, {"puan": 100})
            user_data[p.id]["puan"] -= 30
            cezali_oyuncular[user.id] = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=30)
            log = discord.utils.get(channel.guild.text_channels, name="cezalı-log")
            if log:
                await log.send(f"⛔ {p.mention} hazır olmadı. -30p ceza ve 30dk engel.")
        await channel.send("❌ Maç iptal edildi. Bazı oyuncular hazır olmadı.")
        await asyncio.sleep(5)
        await channel.delete()
        return

    # ✅ Herkes hazır olduysa → oylama başlasın
    await voting_phase(channel, players, alpha_team, beta_team)

from discord.ui import View, Select
import asyncio

async def voting_phase(channel, players, alpha_team, beta_team):
    votes = {"Alpha": 0, "Beta": 0}
    voted_users = {"Alpha": set(), "Beta": set()}

    class VoteView(View):
        def __init__(self, timeout=1800):  # 30 dakika
            super().__init__(timeout=timeout)
            self.vote_result_announced = False

        async def on_timeout(self):
            if not self.vote_result_announced:
                await channel.send("⏰ Oylama süresi doldu! Kazanan belirlenemedi.")
                try:
                    await channel.delete()
                except:
                    pass

    class VoteSelect(Select):
        def __init__(self, parent_view):
            self.parent_view = parent_view
            super().__init__(placeholder="Kazanan takımı seç", options=[
                discord.SelectOption(label="Alpha"),
                discord.SelectOption(label="Beta")
            ])

        async def callback(self, interaction):
            if self.parent_view.vote_result_announced:
                return

            if interaction.user.id not in [p.id for p in players]:
                await interaction.response.send_message("❌ Bu oylamaya katılamazsın.", ephemeral=True)
                return

            previous_vote = None
            for team in votes:
                if interaction.user.id in voted_users[team]:
                    previous_vote = team
                    break

            new_vote = self.values[0]

            if previous_vote == new_vote:
                await interaction.response.send_message("❗ Zaten bu takıma oy verdin.", ephemeral=True)
                return

            if previous_vote:
                votes[previous_vote] -= 1
                voted_users[previous_vote].remove(interaction.user.id)
                await channel.send(f"🔁 {interaction.user.mention} oyunu **{previous_vote}**'dan **{new_vote}**'ya değiştirdi.")
            else:
                await channel.send(f"🗳️ {interaction.user.mention} → {new_vote} takımına oy verdi.")

            votes[new_vote] += 1
            voted_users[new_vote].add(interaction.user.id)

            await interaction.response.send_message(f"{new_vote} için oy verdin!", ephemeral=True)

            if votes[new_vote] >= 4:
                self.parent_view.vote_result_announced = True
                self.parent_view.stop()
                await end_voting(channel, players, alpha_team, beta_team, new_vote)

    view = VoteView()
    vote_select = VoteSelect(view)
    view.add_item(vote_select)
    await channel.send("🗳️ Lütfen kazanan takımı oylayın:", view=view)
    await view.wait()

async def end_voting(channel, players, alpha_team, beta_team, winning_team):
    await channel.send(f"🎉 Kazanan takım: **{winning_team}**")
    await asyncio.sleep(3)

    try:
        await channel.delete()
        await asyncio.sleep(1)
    except:
        pass

    for p in players:
        user_data.setdefault(p.id, {"puan": 100})
        if winning_team == "Alpha" and p in alpha_team:
            user_data[p.id]["puan"] += 30
        elif winning_team == "Beta" and p in beta_team:
            user_data[p.id]["puan"] += 30
        else:
            user_data[p.id]["puan"] -= 15

    for p in players:
        try:
            base_name = p.name.split("-")[0].strip()
            new_nick = f"{base_name} - {user_data[p.id]['puan']}p"
            await p.edit(nick=new_nick)
            await assign_rank_role(p, user_data[p.id]["puan"])
        except Exception as e:
            print(f"[nickname güncelleme hatası] {e}")

    print("=== PUANLAR GÜNCELLENDİ ===")
    for p in players:
        print(f"{p.display_name}: {user_data[p.id]['puan']} puan")

async def setup_server(guild):
    category = discord.utils.get(guild.categories, name="Match Making")
    if not category:
        category = await guild.create_category("Match Making")

    for name in JOIN_CHANNELS.keys() | {"bilgi", "cezalı-log", "unban", "oyun-ici-nickname"}:
        ch = discord.utils.get(guild.text_channels, name=name)
        if not ch:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=False,
                    add_reactions=False
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    manage_channels=True
                )
            }
            ch = await guild.create_text_channel(name, category=category, overwrites=overwrites)

        if name in JOIN_CHANNELS:
            turkey_time = datetime.datetime.now(pytz.timezone("Europe/Istanbul")).strftime("%d %B %Y - %H:%M")
            embed_description = (
                "Katılmak için butona tıklayın.\n\n"
                "**Haritalar:**\n" + "\n".join(MAP_LIST) +
                f"\n\n🕒 Son güncelleme: {turkey_time} (TR)"
            )
            embed = discord.Embed(
                title=f"{name.upper()} LOBİSİ",
                description=embed_description
            )
            view = JoinLeaveView(name)
            msg = await ch.send(embed=embed, view=view)
            join_messages[name] = msg

        elif name == "bilgi":
            await ch.send("📘 Bu kanal sistemin nasıl işlediğini açıklar...")

        elif name == "cezalı-log":
            await ch.send("📕 Cezalı oyuncular buraya yazılır.")

        elif name == "unban":
            await ch.send("✅ Cezası biten oyuncular burada duyurulur.")

        elif name == "oyun-ici-nickname":
            embed = discord.Embed(
                title="🎮 Oyun İçi Nickname Ayarlama",
                description=(
                    "Aşağıdaki butona tıklayarak **1 defaya mahsus** oyun içi isminizi belirleyebilirsiniz.\n\n"
                    "**Dikkat:** Sadece ilk kullanım geçerlidir. Daha sonra değiştiremezsiniz!"
                ),
                color=discord.Color.blue()
            )
            view = NicknameView()
            await ch.send(embed=embed, view=view)
from discord.ext import commands
from discord import app_commands, Permissions

log_channel_id = None  # Global olarak log kanalı ID'si saklanacak

@bot.tree.command(name="setup_logs", description="Bot log kanalını oluşturur.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_logs(interaction: discord.Interaction):
    global log_channel_id
    guild = interaction.guild

    # Eski kanal varsa sil
    existing_log = discord.utils.get(guild.text_channels, name="bot-log")
    if existing_log:
        await existing_log.delete()

    # Kanal izinleri: sadece yöneticiler görebilecek
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }

    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_messages=True)

    new_log = await guild.create_text_channel("bot-log", overwrites=overwrites)
    log_channel_id = new_log.id

    await interaction.response.send_message("✅ Sadece yöneticilere özel log kanalı oluşturuldu: #bot-log", ephemeral=True)
    await send_log(guild, "✅ Yeni bot-log kanalı oluşturuldu.")  # 🔔 Log mesajı burada gönderiliyor


async def send_log(guild, message):
    if log_channel_id is None:
        return
    log_channel = guild.get_channel(log_channel_id)
    if log_channel:
        await log_channel.send(message)

@bot.tree.command(name="cancelq", description="Maçı iptal eder ve kanalı siler. (Yalnızca yetkililer)")
@app_commands.checks.has_permissions(manage_channels=True)
async def cancelq(interaction: discord.Interaction):
    if not interaction.channel.name.startswith(("3v3-general-match", "2v2-general-match")):
        await interaction.response.send_message("❌ Bu komut sadece maç kanallarında kullanılabilir.", ephemeral=True)
        return

    await interaction.channel.send("❌ Maç bir yetkili tarafından iptal edildi.")
    await interaction.response.send_message("✅ Maç iptal edildi ve kanal 3 saniye içinde silinecek.", ephemeral=True)
    await asyncio.sleep(3)
    await interaction.channel.delete()


# Oyuncular arası oylamayla maç bozma
cancel_votes = {}

@bot.tree.command(name="winalpha", description="Alpha takımını manuel olarak kazanan ilan et")
@app_commands.checks.has_permissions(manage_messages=True)
async def winalpha(interaction: discord.Interaction):
    await manuel_kazanan_belirle(interaction, "Alpha")

@bot.tree.command(name="winbeta", description="Beta takımını manuel olarak kazanan ilan et")
@app_commands.checks.has_permissions(manage_messages=True)
async def winbeta(interaction: discord.Interaction):
    await manuel_kazanan_belirle(interaction, "Beta")


async def manuel_kazanan_belirle(interaction: discord.Interaction, kazanan_team: str):
    channel = interaction.channel

    if channel.name not in maç_kanalları:
        await interaction.response.send_message("❌ Bu kanal bir maç kanalı değil veya kayıtlı değil.", ephemeral=True)
        return

    players, alpha_team, beta_team = maç_kanalları[channel.name]

    await interaction.response.send_message(f"🛠️ Manuel olarak **{kazanan_team}** takımı kazanan ilan edildi.")
    await send_log(interaction.guild, f"🛠️ {kazanan_team} takımı manuel kazanan olarak ilan edildi. Kanal: #{channel.name}")

    await asyncio.sleep(2)

    # Puanları güncelle
    for p in players:
        user_data.setdefault(p.id, {"puan": 100})
        if kazanan_team == "Alpha" and p in alpha_team:
            user_data[p.id]["puan"] += 30
        elif kazanan_team == "Beta" and p in beta_team:
            user_data[p.id]["puan"] += 30
        else:
            user_data[p.id]["puan"] -= 15

    # Nickname güncelle
    try:
        for p in players:
            base_name = p.name.split("-")[0].strip()
            new_nick = f"{base_name} - {user_data[p.id]['puan']}p"
            await p.edit(nick=new_nick)
    except Exception as e:
        print(f"[nickname güncelleme hatası] {e}")

    await asyncio.sleep(3)
    await channel.send(f"🎉 **{kazanan_team}** takımı manuel olarak galip ilan edildi. Maç sonlandırılıyor...")
    await asyncio.sleep(3)

    # Kanal kaydını sil ve kanalı kapat
    del maç_kanalları[channel.name]
    await channel.delete()

@bot.tree.command(name="macboz", description="Oyuncuların ortak kararıyla maçı iptal eder (oy birliği gerekir).")
async def macboz(interaction: discord.Interaction):
    channel = interaction.channel
    channel_name = channel.name

    if not channel_name.startswith(("3v3-general-match", "2v2-general-match")):
        await interaction.response.send_message("❌ Bu komut sadece maç kanallarında kullanılabilir.", ephemeral=True)
        return

    if channel.id not in cancel_votes:
        cancel_votes[channel.id] = set()

    cancel_votes[channel.id].add(interaction.user.id)

    current_votes = len(cancel_votes[channel.id])
    required_votes = 6 if channel_name.startswith("3v3") else 4

    await interaction.response.send_message(f"🗳️ Maçı bozmak isteyen kişi sayısı: **{current_votes}/{required_votes}**", ephemeral=True)

    if current_votes >= required_votes:
        await channel.send("❌ Oyuncuların ortak kararıyla maç iptal edildi.")
        await asyncio.sleep(3)
        await channel.delete()
        cancel_votes.pop(channel.id, None)
        
@bot.tree.command(name="setup")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    # Önce hemen geçici cevap ver
    await interaction.response.defer(ephemeral=True)
    
    # Ardından kurulumu yap
    await setup_server(interaction.guild)

    # Son cevabı gönder
    await interaction.followup.send("✅ Kurulum tamamlandı!", ephemeral=True)

from discord.ext import commands

def get_rank(puan):
    for rank, (min_puan, max_puan) in RANKLAR.items():
        if min_puan <= puan <= max_puan:
            return rank
    return "🥉 Bronze"  # Varsayılan olarak en düşük rank

@bot.tree.command(name="update_names", description="Tüm üyelerin ismine puanını ekler.")
@app_commands.checks.has_permissions(administrator=True)
async def update_names(interaction: discord.Interaction):
    count = 0
    failed = []

    for member in interaction.guild.members:
        if member.bot:
            continue

        if member.id == interaction.guild.owner_id:
            failed.append(f"{member.display_name} 🔒 (Sunucu sahibinin ismi değiştirilemez)")
            continue

        user_data.setdefault(member.id, {"puan": 100})
        puan = user_data[member.id]["puan"]

        base_name = member.name.split("-")[0].strip()
        new_name = f"{base_name} - {puan}p"

        try:
            await member.edit(nick=new_name)
            count += 1
        except discord.Forbidden:
            failed.append(f"{member.display_name} ❌ (Yetki yetersiz)")
        except discord.HTTPException as e:
            failed.append(f"{member.display_name} ⚠️ ({str(e)[:50]})")

    msg = f"✅ {count} üyenin ismi güncellendi."
    if failed:
        msg += f"\n\n🚫 Değiştirilemeyenler:\n" + "\n".join(failed[:10])

    await interaction.response.send_message(msg, ephemeral=True)
    
@bot.tree.command(name="mesaj", description="Botun mesaj göndermesini sağlar.")
@app_commands.describe(icerik="Botun göndereceği mesaj")
@app_commands.checks.has_permissions(manage_messages=True)  # sadece yetkililer kullanabilir
async def mesaj(interaction: discord.Interaction, icerik: str):
    await interaction.channel.send(icerik)
    await interaction.response.send_message("✅ Mesaj gönderildi.", ephemeral=True)
    
@bot.tree.command(name="reroll", description="Rastgele seçilen haritanın yeniden çekilmesi için oy kullan.")
async def reroll(interaction: discord.Interaction):
    channel = interaction.channel
    user_id = interaction.user.id
    channel_id = channel.id

    if channel_id in reroll_done:
        await interaction.response.send_message("❌ Bu maçta zaten bir kez yeniden harita seçildi.", ephemeral=True)
        return

    if channel_id not in map_data:
        await interaction.response.send_message("❌ Harita seçimi yapılmadan reroll yapılamaz.", ephemeral=True)
        return

    if channel_id not in reroll_requests:
        reroll_requests[channel_id] = []

    if user_id in reroll_requests[channel_id]:
        await interaction.response.send_message("❗ Zaten reroll oyu verdin.", ephemeral=True)
        return

    reroll_requests[channel_id].append(user_id)

    if len(reroll_requests[channel_id]) >= 4:
        reroll_done.add(channel_id)
        kullanicilar = reroll_requests[channel_id]
        onceki_harita = map_data[channel_id]
        kalan_haritalar = [h for h in HARITALAR if h != onceki_harita]
        yeni_harita = random.choice(kalan_haritalar)
        map_data[channel_id] = yeni_harita

        etiketler = " ".join([f"<@{uid}>" for uid in kullanicilar])
        await channel.send(f"🔁 Harita yeniden çekildi! Reroll oyu verenler: {etiketler}\n🗺 Yeni harita: **{yeni_harita}**")

    else:
        await interaction.response.send_message(
            f"✅ Reroll oyu verildi. ({len(reroll_requests[channel_id])}/4)", ephemeral=True
        )

@bot.tree.command(name="ban")
@app_commands.describe(user="Banlanacak kullanıcı", sure="Ceza süresi (dakika)")
@app_commands.checks.has_permissions(administrator=True)
async def ban(interaction: discord.Interaction, user: discord.Member, sure: int):
    cezali_oyuncular[user.id] = datetime.datetime.utcnow() + datetime.timedelta(minutes=sure)
    log = discord.utils.get(interaction.guild.text_channels, name="cezalı-log")
    if log:
        await log.send(f"⛔ {user.mention} {sure} dakikalığına manuel olarak banlandı.")
    await interaction.response.send_message(f"{user.mention} adlı kullanıcıya ceza verildi.", ephemeral=True)

@bot.tree.command(name="unban", description="Belirtilen kullanıcının cezasını kaldırır.")
@app_commands.describe(user="Banı kaldırılacak kullanıcı")
@app_commands.checks.has_permissions(administrator=True)
async def unban(interaction: discord.Interaction, user: discord.Member):
    if user.id in cezali_oyuncular:
        cezali_oyuncular.pop(user.id)
        unban_ch = discord.utils.get(interaction.guild.text_channels, name="unban")
        if unban_ch:
            await unban_ch.send(f"✅ {user.mention}’in cezası manuel olarak kaldırıldı.")
        await interaction.response.send_message(f"{user.mention} artık cezalı değil.", ephemeral=True)
    else:
        await interaction.response.send_message(f"{user.mention} şu anda cezalı değil.", ephemeral=True)

@bot.tree.command(name="bilgi", description="Sistemin nasıl çalıştığını açıklar.")
@app_commands.checks.has_permissions(manage_messages=True)
async def bilgi(interaction: discord.Interaction):
    bilgi_mesaji = (
        "📌 **xdecahx Matchmaking Sistemi Bilgilendirmesi**\n\n"
        "Merhaba oyuncular! Sunucumuzda adil ve eğlenceli karşılaşmalar için geliştirilmiş olan özel bir matchmaking (eşleşme) sistemi kullanılmaktadır. "
        "Aşağıda sistemin nasıl işlediğini adım adım öğrenebilirsiniz:\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🎮 **1. Katılım Sistemi**\n"
        "• `#3v3-general` → 6 KİŞİLİK MAÇ\n"
        "• `#2v2-general` → 4 KİŞİLİK MAÇ\n"
        "→ Join butonuna tıklayarak sıraya girebilirsiniz.\n"
        "→ Oyuncu sayısı tamamlanınca maç kanalı otomatik açılır.\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🧠 **2. Kaptan Seçimi ve Takım Dağılımı**\n"
        "• 3v3'te 2 kaptan rastgele seçilir.\n"
        "• Kaptanlar sırayla oyuncu seçerek Alpha & Beta takımlarını oluşturur.\n"
        "• 2v2'de takımlar rastgele belirlenir.\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🗺️ **3. Harita Banlama Süreci**\n"
        "• Toplam 9 harita listelenir.\n"
        "• Önce Alpha, sonra Beta kaptanı 1’er ban yapar.\n"
        "• Kalan haritalardan biri rastgele seçilir.\n"
        "⏱️ Süre: her kaptan için **2 dakika**\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "✅ **4. Ready (Hazır) Sistemi**\n"
        "• Oyuncular 2 dakika içinde '✅ Hazırım' butonuna basmalıdır.\n"
        "• Hazır olmayanlar:\n"
        "   - 30dk cezalı olur\n"
        "   - -30 puan cezası alır\n"
        "   - Maç iptal edilir\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🏆 **5. Oylama Sistemi**\n"
        "• Her oyuncu kazanan takımı oylayabilir.\n"
        "• Bir takıma 4 oy gelirse o takım kazanır.\n"
        ". Oylama yanlış oylama yapıldığı takdirde oylama değiştirilebilir.\n"
        ". Bilerek  doğru takıma oy vermeyen oyuncular şikayet edildiğinde ceza alacaktır.\n"
        "🎉 Kazanan Takım: +30 puan\n"
        "😢 Kaybeden Takım: -15 puan\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📊 **6. Puan & Rütbe Sistemi**\n"
        "• Başlangıç puanı: **100p**\n"
        "• Rütbeler:\n"
        "   🥉 Bronze 100p\n"
        "   🥈 Silver 500p\n"
        "   🥇 Gold 1000p\n"
        "   💎 Diamond 1400p\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "⛔ **7. Ceza Sistemi**\n"
        "• Hazır olmayan veya kurallara uymayanlar cezalı olur.\n"
        "• `#cezalı-log` kanalında duyurulur.\n"
        "• Süre bitince `#unban` kanalında bildirilir.\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Her maç puan sisteminizi etkiler. Adil ve keyifli oyunlar! 🎮"
    )

    await interaction.channel.send(bilgi_mesaji)
    await interaction.response.send_message("✅ Bilgi mesajı gönderildi.", ephemeral=True)
        
@bot.tree.command(name="sync", description="Komutları Discord ile senkronize eder.")
@app_commands.checks.has_permissions(administrator=True)
async def sync(interaction: discord.Interaction):
    await bot.tree.sync(guild=interaction.guild)
    await interaction.response.send_message("✅ Bu sunucuya özel komutlar senkronize edildi.", ephemeral=True)

@bot.tree.command(name="puanver", description="Belirtilen kullanıcıya puan ekler.")
@app_commands.describe(user="Puan verilecek kullanıcı", miktar="Eklenecek puan miktarı")
@app_commands.checks.has_permissions(administrator=True)
async def puanver(interaction: discord.Interaction, user: discord.Member, miktar: int):
    eski_isim = user.display_name
    mevcut_puan = extract_point_from_name(eski_isim)
    yeni_puan = mevcut_puan + miktar

    try:
        yeni_isim = eski_isim.rsplit("-", 1)[0].strip() + f" - {yeni_puan}p"
        await user.edit(nick=yeni_isim)

        # ✅ Rank verisini güncelle
        rank_data = load_rank_data()
        rank_data[str(user.id)] = {
            "point": yeni_puan,
            "rank": get_rank_name(yeni_puan),
        }
        save_rank_data(rank_data)

        # ✅ Rank rolünü güncelle
        await assign_rank_role(user, yeni_puan)

        await interaction.response.send_message(f"✅ {user.mention} adlı kullanıcıya {miktar}p eklendi. Yeni puanı: {yeni_puan}p", ephemeral=True)
    except:
        await interaction.response.send_message("❌ Kullanıcının ismi değiştirilemedi.", ephemeral=True)

@bot.tree.command(name="puansil", description="Belirtilen kullanıcının puanını azaltır.")
@app_commands.describe(user="Puanı silinecek kullanıcı", miktar="Çıkarılacak puan miktarı")
@app_commands.checks.has_permissions(administrator=True)
async def puansil(interaction: discord.Interaction, user: discord.Member, miktar: int):
    eski_isim = user.display_name
    mevcut_puan = extract_point_from_name(eski_isim)
    yeni_puan = max(100, mevcut_puan - miktar)

    try:
        yeni_isim = eski_isim.rsplit("-", 1)[0].strip() + f" - {yeni_puan}p"
        await user.edit(nick=yeni_isim)

        # ✅ Rank verisini güncelle
        rank_data = load_rank_data()
        rank_data[str(user.id)] = {
            "point": yeni_puan,
            "rank": get_rank_name(yeni_puan),
        }
        save_rank_data(rank_data)

        # ✅ Rank rolünü güncelle
        await assign_rank_role(user, yeni_puan)

        await interaction.response.send_message(
            f"✅ {user.mention} adlı kullanıcının puanı güncellendi. Yeni puanı: {yeni_puan}p",
            ephemeral=True
        )
    except:
        await interaction.response.send_message("❌ Kullanıcının ismi değiştirilemedi.", ephemeral=True)

from discord.ext import tasks
import datetime

@tasks.loop(minutes=1)
async def check_unbans():
    now = datetime.datetime.now(datetime.timezone.utc)
    for user_id in list(cezali_oyuncular.keys()):
        if cezali_oyuncular[user_id] <= now:
            cezali_oyuncular.pop(user_id)
            for guild in bot.guilds:
                user = guild.get_member(user_id)
                unban_ch = discord.utils.get(guild.text_channels, name="unban")
                if unban_ch and user:
                    await unban_ch.send(f"✅ {user.mention}’in cezası sona erdi. Tekrar katılabilir!")

@bot.event
async def on_ready():
    print(f"{bot.user} giriş yaptı.")
    await bot.tree.sync()

    # ✅ Yeni kullanıcıları JSON'a ekle
    rank_data = load_rank_data()

    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue

            user_id = str(member.id)

            if user_id not in rank_data:
                # Başlangıç puanı ve rank
                rank_data[user_id] = {
                    "rank": "🥉 Bronze",
                    "point": 100,
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                print(f"{member.name} eklendi → 100p")

    save_rank_data(rank_data)  # ✅ JSON dosyasına yaz

    # 🔁 setup_server ve rank güncellemeleri
    for guild in bot.guilds:
        await setup_server(guild)

        for member in guild.members:
            if member.bot:
                continue

            user_data = rank_data.get(str(member.id))
            if user_data:
                puan = user_data.get("point", 0)

                # Mevcut rank rolünü bul
                mevcut_rol = None
                for rol_adi in RANKLAR.keys():
                    rol = discord.utils.get(guild.roles, name=rol_adi)
                    if rol and rol in member.roles:
                        mevcut_rol = rol_adi
                        break

                # Hedef rank rolünü puana göre belirle
                hedef_rol = None
                for rol_adi, (min_puan, max_puan) in RANKLAR.items():
                    if min_puan <= puan <= max_puan:
                        hedef_rol = rol_adi
                        break

                # Eğer rol farklıysa, güncelle
                if mevcut_rol != hedef_rol:
                    await assign_rank_role(member, puan)

    # rank_data'daki tüm kullanıcıları kontrol et
    for guild in bot.guilds:
        for user_id, data in rank_data.items():
            member = guild.get_member(int(user_id))
            if member:
                await assign_rank_role(member, data.get("point", 0))

    # Sürekli görevleri başlat
    rank_auto_loop.start()
    check_unbans.start()

bot.run(TOKEN)
