from __future__ import annotations

import html


def search_page_html(*, community_name: str, brand_logo_url: str) -> str:
    community = html.escape(community_name)
    brand_logo = html.escape(brand_logo_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#7f2528">
<title>Search Pokémon Events · PokÈvent</title>
<style>
:root {{ color-scheme:light; --bg:#f5f1ed; --panel:#fffdfb; --text:#2c2323; --muted:#756866; --line:#ddcfca; --accent:#8d292d; --accent-dark:#692025; --accent-soft:#f2dedd; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:linear-gradient(180deg,#fff 0,#f8f4f1 210px,var(--bg) 520px); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif }}
button,input {{ font:inherit }}
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
.search-panel {{ background:var(--panel); border:1px solid var(--line); border-radius:22px; padding:22px; box-shadow:0 8px 28px rgba(73,43,38,.07); margin-bottom:20px }}
.search-panel h2 {{ margin-bottom:7px }}
.search-panel p {{ color:var(--muted); margin-bottom:16px }}
.search-row {{ display:grid; grid-template-columns:1fr 150px auto; gap:9px }}
input,select {{ width:100%; border:1px solid var(--line); border-radius:11px; padding:12px 14px; background:#fff; color:var(--text); font:inherit }}
button {{ border:0; border-radius:11px; padding:12px 18px; color:#fff; background:var(--accent); font-weight:800; cursor:pointer }}
button:hover {{ background:var(--accent-dark) }}
.toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin:18px 0 }}
.toolbar h2 {{ margin:0; font-size:20px }}
.meta {{ color:var(--muted) }}
.results {{ display:grid; gap:12px }}
.event-card {{ display:grid; grid-template-columns:64px 1fr auto; gap:15px; align-items:center; background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:15px }}
.league-logo,.league-fallback {{ width:58px; height:58px; border-radius:15px; object-fit:contain; background:#fff; border:1px solid var(--line); padding:4px }}
.league-fallback {{ display:grid; place-items:center; color:var(--accent); font-size:22px; font-weight:900 }}
.event-card h3 {{ margin-bottom:4px }}
.location {{ color:var(--muted); margin-top:3px }}
.tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px }}
.tag {{ font-size:11px; padding:4px 7px; border-radius:999px; background:#f0e4df; color:var(--accent-dark) }}
.actions {{ display:flex; gap:7px; justify-content:flex-end; margin-top:9px }}
.action {{ text-decoration:none; border:1px solid var(--line); border-radius:9px; padding:7px 9px; background:#fff; color:var(--accent-dark); font-size:12px; font-weight:700 }}
.action.primary {{ color:#fff; background:var(--accent); border-color:var(--accent) }}
.date-block {{ text-align:right; min-width:112px }}
.date-block strong {{ display:block; font-size:17px }}
.empty {{ padding:44px 20px; text-align:center; color:var(--muted); border:1px dashed var(--line); border-radius:18px; background:rgba(255,255,255,.45) }}
footer {{ margin-top:22px; text-align:center; color:var(--muted); font-size:12px }}
@media(max-width:760px) {{
  header {{ align-items:flex-start }}
  .brand-logo {{ width:84px; height:84px }}
  .search-row {{ grid-template-columns:1fr }}
  .event-card {{ grid-template-columns:52px 1fr }}
  .league-logo,.league-fallback {{ width:48px; height:48px; border-radius:12px }}
  .date-block {{ grid-column:2; text-align:left }}
  .actions {{ justify-content:flex-start }}
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
  <a href="/search" class="active">Search</a>
  <a href="/bot">Bot Info</a>
</nav>

<section class="search-panel">
  <h2>Find Pokémon events</h2>
  <p>Search the live Play! Pokémon event catalogue around a UK town or postcode.</p>
  <form id="searchForm" class="search-row">
    <input id="query" type="search" maxlength="100" autocomplete="postal-code" placeholder="e.g. Swindon, Bath or SN1 1AA">
    <select id="radius" aria-label="Search radius">
      <option value="10">10 miles</option>
      <option value="25" selected>25 miles</option>
      <option value="50">50 miles</option>
    </select>
    <button type="submit">Search events</button>
  </form>
</section>

<section>
  <div class="toolbar">
    <h2 id="heading">Search results</h2>
    <span class="meta" id="resultCount"></span>
  </div>
  <div id="results" class="results">
    <div class="empty">Enter a UK town or postcode to search the live event catalogue.</div>
  </div>
</section>

<footer>PokÈvent 3.0 · {community}</footer>
</main>
<script>
var gameLabels={{tcg:"Pokémon TCG",vgc:"Pokémon VGC",go:"Pokémon GO"}};
function esc(v){{return String(v==null?"":v).replace(/[&<>"']/g,function(c){{return {{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c]}})}}
function gameLabel(v){{return gameLabels[String(v||"").toLowerCase()]||String(v||"Pokémon")}}
function logo(e){{return e.league_logo?'<img class="league-logo" src="'+esc(e.league_logo)+'" alt="">':'<div class="league-fallback">P</div>'}}
function dateOnly(v){{return new Intl.DateTimeFormat(undefined,{{weekday:"short",day:"numeric",month:"short"}}).format(new Date(v))}}
function timeOnly(v){{return new Date(v).toLocaleTimeString([],{{hour:"2-digit",minute:"2-digit"}})}}
function render(rows,q){{
  var results=document.getElementById("results");
  document.getElementById("resultCount").textContent=rows.length+" event"+(rows.length===1?"":"s");
  document.getElementById("heading").textContent=q?'Results for “'+q+'”':"Search results";
  if(!rows.length){{
    results.innerHTML='<div class="empty">No upcoming events matched that location in the current PokÈvent catalogue.</div>';
    return;
  }}
  results.innerHTML=rows.map(function(e){{
    var location=[e.venue_name,e.address,e.city,e.postcode].filter(Boolean).join(", ");
    var links="";
    if(e.source_url)links+='<a class="action primary" target="_blank" rel="noopener" href="'+esc(e.source_url)+'">View event</a>';
    if(e.registration_url)links+='<a class="action" target="_blank" rel="noopener" href="'+esc(e.registration_url)+'">Register</a>';
    return '<article class="event-card">'+logo(e)
      +'<div><h3>'+esc(e.title)+'</h3>'
      +'<div class="meta">'+esc(e.league_name||"Play! Pokémon")+'</div>'
      +'<div class="location">'+esc(location||"Location TBC")+'</div>'
      +'<div class="tags"><span class="tag">'+esc(gameLabel(e.game))+'</span><span class="tag">'+esc(e.event_type||"Event")+'</span></div>'
      +(links?'<div class="actions">'+links+'</div>':"")
      +'</div><div class="date-block"><strong>'+esc(dateOnly(e.starts_at))+'</strong><span class="meta">'+esc(timeOnly(e.starts_at))+'</span></div></article>';
  }}).join("");
}}
async function runSearch(q,radius){{
  q=(q||"").trim();
  if(q.length<2){{
    document.getElementById("resultCount").textContent="";
    document.getElementById("heading").textContent="Search results";
    document.getElementById("results").innerHTML='<div class="empty">Enter at least two characters to search for upcoming events.</div>';
    return;
  }}
  document.getElementById("results").innerHTML='<div class="empty">Searching…</div>';
  try{{
    var response=await fetch("/api/search?q="+encodeURIComponent(q)+"&radius="+encodeURIComponent(radius),{{cache:"no-store"}});
    var data=await response.json();
    if(!response.ok)throw new Error(data.detail||"Search failed");
    render(data.events||[],data.location&&data.location.label?data.location.label:q);
  }}catch(error){{
    document.getElementById("results").innerHTML='<div class="empty">Search is temporarily unavailable.</div>';
  }}
}}
document.getElementById("searchForm").addEventListener("submit",function(event){{
  event.preventDefault();
  var q=document.getElementById("query").value.trim();
  var radius=document.getElementById("radius").value;
  var url=new URL(window.location.href);
  if(q)url.searchParams.set("q",q);else url.searchParams.delete("q");
  url.searchParams.set("radius",radius);
  history.replaceState(null,"",url);
  runSearch(q,radius);
}});
var params=new URLSearchParams(location.search);
var initial=params.get("q")||"";
var initialRadius=params.get("radius")||"25";
if(["10","25","50"].includes(initialRadius))document.getElementById("radius").value=initialRadius;
if(initial){{
  document.getElementById("query").value=initial;
  runSearch(initial,document.getElementById("radius").value);
}}
</script>
</body>
</html>"""
