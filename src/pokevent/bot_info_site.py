from __future__ import annotations

import html


def bot_info_html(*, community_name: str, brand_logo_url: str) -> str:
    community = html.escape(community_name)
    brand_logo = html.escape(brand_logo_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#7f2528">
<title>PokÈvent Bot Info · {community}</title>
<style>
:root {{ color-scheme:light; --bg:#f5f1ed; --panel:#fffdfb; --text:#2c2323; --muted:#756866; --line:#ddcfca; --accent:#8d292d; --accent-dark:#692025; --accent-soft:#f2dedd; --green:#2f7d4a; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:linear-gradient(180deg,#fff 0,#f8f4f1 210px,var(--bg) 520px); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif }}
a {{ color:inherit }}
.shell {{ width:min(1180px,calc(100% - 28px)); margin:auto; padding:34px 0 70px }}
header {{ display:flex; align-items:center; gap:18px; margin-bottom:20px }}
.brand-logo {{ width:112px; height:112px; object-fit:contain; flex:0 0 auto; filter:drop-shadow(0 6px 14px rgba(82,32,33,.14)) }}
.eyebrow {{ color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; margin-bottom:3px }}
h1,h2,h3,p {{ margin-top:0 }}
h1 {{ margin-bottom:0; font-size:clamp(28px,4vw,40px); letter-spacing:-.04em }}
.site-nav {{ display:flex; gap:8px; margin:0 0 26px }}
.site-nav a {{ text-decoration:none; padding:9px 13px; border:1px solid var(--line); border-radius:10px; background:#fff; color:var(--accent-dark); font-weight:700 }}
.site-nav a.active {{ background:var(--accent); color:#fff; border-color:var(--accent) }}
.hero {{ background:var(--panel); border:1px solid var(--line); border-radius:22px; padding:24px; box-shadow:0 8px 28px rgba(73,43,38,.07); margin-bottom:18px }}
.hero-row {{ display:flex; justify-content:space-between; gap:24px; align-items:center }}
.bot-heading {{ display:flex; align-items:center; gap:16px }}
.bot-avatar {{ width:74px; height:74px; border-radius:18px; object-fit:cover; border:1px solid var(--line); background:#fff; display:none }}
.bot-avatar.visible {{ display:block }}
.hero p {{ margin:8px 0 0; color:var(--muted); max-width:680px }}
.invite {{ display:inline-block; flex:0 0 auto; text-decoration:none; color:#fff; background:var(--accent); padding:12px 17px; border-radius:11px; font-weight:800 }}
.invite:hover {{ background:var(--accent-dark) }}
.invite.disabled {{ pointer-events:none; opacity:.45 }}
.stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:18px }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:18px }}
.stat small {{ display:block; color:var(--muted); margin-bottom:5px }}
.stat strong {{ font-size:24px; letter-spacing:-.03em }}
.status-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; background:#a8a2a0; margin-right:7px }}
.status-dot.online {{ background:var(--green); box-shadow:0 0 0 5px rgba(47,125,74,.1) }}
.grid {{ display:grid; grid-template-columns:1.35fr .65fr; gap:18px }}
.commands {{ margin-top:18px }}
.command-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px }}
.command {{ background:#f8f1ee; border:1px solid #eadfda; border-radius:12px; padding:13px 14px }}
.command code {{ display:block; color:var(--accent-dark); font-weight:800; margin-bottom:4px; font-size:14px }}
.command span {{ color:var(--muted) }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:20px }}
.panel h2 {{ font-size:19px; margin-bottom:12px }}
.features {{ display:grid; gap:9px }}
.feature {{ background:#f8f1ee; border:1px solid #eadfda; border-radius:12px; padding:12px 14px }}
.feature strong {{ display:block; margin-bottom:2px }}
.meta {{ color:var(--muted) }}
.kv {{ display:grid; gap:10px }}
.kv-row {{ display:flex; justify-content:space-between; gap:16px; border-bottom:1px solid #eee3df; padding-bottom:10px }}
.kv-row:last-child {{ border:0; padding-bottom:0 }}
.kv-row span:first-child {{ color:var(--muted) }}
footer {{ margin-top:20px; text-align:center; color:var(--muted); font-size:12px }}
@media(max-width:760px) {{
  header {{ align-items:flex-start }}
  .brand-logo {{ width:84px; height:84px }}
  .hero-row {{ display:block }}
  .invite {{ margin-top:16px }}
  .stats {{ grid-template-columns:1fr 1fr }}
  .grid {{ grid-template-columns:1fr }}
  .command-list {{ grid-template-columns:1fr }}
}}
@media(max-width:460px) {{
  .stats {{ grid-template-columns:1fr }}
}}
</style>
</head>
<body>
<main class="shell">
<header>
  <img class="brand-logo" src="{brand_logo}" alt="PokÈvent 3.0">
  <div><div class="eyebrow">Play • Trade • Battle</div><h1>PokÈvent</h1></div>
</header>
<nav class="site-nav" aria-label="PokÈvent">
  <a href="/">Events</a>
  <a href="https://events.pokemon.com/EventLocator/?locale=en-us" target="_blank" rel="noopener">Find Events</a>
  <a href="/bot" class="active">Bot Info</a>
</nav>

<section class="hero">
  <div class="hero-row">
    <div class="bot-heading">
      <img id="botAvatar" class="bot-avatar" alt="PokÈvent Discord bot avatar">
      <div>
        <h2>PokÈvent Discord Bot</h2>
        <p>Event discovery, announcements, rolling League summaries, discussion threads, lifecycle updates and optional community welcomes for local Pokémon servers.</p>
      </div>
    </div>
    <a id="inviteButton" class="invite disabled" href="#" rel="noopener">Add PokÈvent to your server</a>
  </div>
</section>

<section class="stats">
  <div class="stat"><small>Status</small><strong><span id="statusDot" class="status-dot"></span><span id="status">Checking…</span></strong></div>
  <div class="stat"><small>Uptime</small><strong id="uptime">—</strong></div>
  <div class="stat"><small>Discord servers</small><strong id="servers">—</strong></div>
  <div class="stat"><small>Version</small><strong id="version">—</strong></div>
</section>

<section class="panel commands">
  <h2>Discord commands</h2>
  <div class="command-list">
    <div class="command"><code>/events [league]</code><span>Browse upcoming events for the server's default League or another configured League.</span></div>
    <div class="command"><code>/calendar</code><span>Get a private link to the public PokÈvent calendar.</span></div>
    <div class="command"><code>/pokevent setup</code><span>Administrator dashboard for Leagues, channels, event types, notifications, welcomes, posting tools and manual event checks.</span></div>
    <div class="command"><code>/pokevent status</code><span>Show the current PokÈvent configuration and routing status for the Discord server.</span></div>
  </div>
</section>

<section class="grid">
  <div class="panel">
    <h2>What PokÈvent does</h2>
    <div class="features">
      <div class="feature"><strong>🎟️ Event announcements</strong><span class="meta">Posts configured tournament types as rich Discord cards with optional role or @everyone notifications.</span></div>
      <div class="feature"><strong>📌 Rolling event summary</strong><span class="meta">Keeps a pinned summary of upcoming events for each configured announcement channel.</span></div>
      <div class="feature"><strong>💬 Event discussion threads</strong><span class="meta">Creates a discussion thread for announced events and keeps it updated when event details change.</span></div>
      <div class="feature"><strong>🔄 Lifecycle tracking</strong><span class="meta">Updates cards for time, venue and registration changes and clearly marks cancellations.</span></div>
      <div class="feature"><strong>👋 Optional member welcomes</strong><span class="meta">Can welcome new members using Pokémon-themed text or generated image banners.</span></div>
    </div>
  </div>
  <div class="panel">
    <h2>Live information</h2>
    <div class="kv">
      <div class="kv-row"><span>Bot account</span><strong id="botName">—</strong></div>
      <div class="kv-row"><span>Configured Leagues</span><strong id="leagueCount">—</strong></div>
      <div class="kv-row"><span>Last heartbeat</span><strong id="heartbeat">—</strong></div>
    </div>
  </div>
</section>

<footer>PokÈvent 3.0 · {community}</footer>
</main>
<script>
function duration(seconds) {{
  seconds=Math.max(0,Math.floor(Number(seconds)||0));
  var d=Math.floor(seconds/86400); seconds%=86400;
  var h=Math.floor(seconds/3600); seconds%=3600;
  var m=Math.floor(seconds/60);
  var parts=[];
  if(d)parts.push(d+"d");
  if(h||d)parts.push(h+"h");
  parts.push(m+"m");
  return parts.join(" ");
}}
async function refreshBotInfo() {{
  try {{
    var response=await fetch("/api/bot",{{cache:"no-store"}});
    var data=await response.json();
    document.getElementById("status").textContent=data.online?"Online":"Offline";
    document.getElementById("statusDot").classList.toggle("online",Boolean(data.online));
    document.getElementById("uptime").textContent=data.uptime_seconds==null?"—":duration(data.uptime_seconds);
    document.getElementById("servers").textContent=data.server_count==null?"—":data.server_count.toLocaleString();
    document.getElementById("version").textContent=data.version||"—";
    document.getElementById("botName").textContent=data.bot_name||"—";
    document.getElementById("leagueCount").textContent=data.configured_league_count==null?"—":data.configured_league_count;
    document.getElementById("heartbeat").textContent=data.last_seen_at?new Date(data.last_seen_at).toLocaleString():"—";
    var avatar=document.getElementById("botAvatar");
    if(data.avatar_url) {{
      avatar.src=data.avatar_url;
      avatar.classList.add("visible");
    }} else {{
      avatar.removeAttribute("src");
      avatar.classList.remove("visible");
    }}
    var invite=document.getElementById("inviteButton");
    if(data.invite_url) {{
      invite.href=data.invite_url;
      invite.classList.remove("disabled");
      invite.target="_blank";
    }} else {{
      invite.href="#";
      invite.classList.add("disabled");
      invite.removeAttribute("target");
    }}
  }} catch(error) {{
    document.getElementById("status").textContent="Unavailable";
    document.getElementById("statusDot").classList.remove("online");
  }}
}}
refreshBotInfo();
setInterval(refreshBotInfo,30000);
</script>
</body>
</html>"""
