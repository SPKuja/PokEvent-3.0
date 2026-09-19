from __future__ import annotations

import html


def public_index_html(*, community_name: str, home_name: str) -> str:
    community = html.escape(community_name)
    home = html.escape(home_name)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111318">
<title>PokÈvent · {community}</title>
<style>
:root {{ color-scheme:dark; --bg:#0d0f13; --panel:#171a21; --panel2:#20242d; --text:#f4f5f7; --muted:#a7adba; --line:#2c313d; --accent:#ef5350; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:radial-gradient(circle at 15% -10%,rgba(239,83,80,.14),transparent 34rem),var(--bg); color:var(--text); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif }}
button,select {{ font:inherit }}
a {{ color:inherit }}
.shell {{ width:min(1180px,calc(100% - 28px)); margin:auto; padding:34px 0 70px }}
header {{ display:flex; align-items:center; gap:14px; margin-bottom:28px }}
.brandmark {{ width:48px; height:48px; border-radius:50%; display:grid; place-items:center; font-weight:900; font-size:21px; color:#fff; background:linear-gradient(180deg,var(--accent) 0 49%,#fff 49% 56%,#171a21 56%); border:2px solid #fff }}
h1,h2,h3,p {{ margin-top:0 }}
h1 {{ margin-bottom:2px; font-size:clamp(28px,4vw,40px); letter-spacing:-.04em }}
.subtitle,.meta {{ color:var(--muted) }}
.subtitle {{ margin:0 }}
.controls {{ display:grid; grid-template-columns:auto 1fr; gap:12px; background:rgba(23,26,33,.94); border:1px solid var(--line); border-radius:18px; padding:12px; margin-bottom:22px }}
.switcher {{ display:flex; background:#111318; padding:4px; border-radius:13px }}
.switcher button,.ghost,.primary {{ border:0; border-radius:10px; padding:10px 14px; cursor:pointer }}
.switcher button {{ color:var(--muted); background:transparent }}
.switcher button.active {{ background:var(--panel2); color:var(--text) }}
.filters {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px }}
select {{ width:100%; padding:10px 12px; border-radius:10px; border:1px solid var(--line); background:#111318; color:var(--text) }}
.toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin:18px 0 }}
.toolbar h2 {{ margin:0; font-size:20px }}
.month-nav {{ display:flex; gap:7px }}
.ghost {{ background:var(--panel); color:var(--text); border:1px solid var(--line); text-decoration:none; display:inline-block }}
.primary {{ background:var(--accent); color:#fff; text-decoration:none; display:inline-block }}
.calendar {{ display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); border:1px solid var(--line); border-radius:18px; overflow:hidden; background:var(--panel) }}
.weekday {{ padding:10px; color:var(--muted); font-size:12px; text-align:center; border-bottom:1px solid var(--line) }}
.day {{ min-height:128px; padding:8px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--panel) }}
.day.outside {{ opacity:.3 }}
.day-number {{ color:var(--muted); font-size:12px; margin-bottom:7px }}
.event-pill {{ display:block; width:100%; text-align:left; border:0; cursor:pointer; color:var(--text); background:var(--panel2); border-left:3px solid var(--accent); border-radius:8px; padding:7px 8px; margin-bottom:6px; font-size:12px }}
.event-pill.cancelled {{ opacity:.6; text-decoration:line-through }}
.list {{ display:grid; gap:12px }}
.event-card {{ display:grid; grid-template-columns:64px 1fr auto; gap:15px; align-items:center; background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:15px; cursor:pointer }}
.event-card:hover {{ border-color:#4c5362 }}
.league-logo,.league-fallback {{ width:58px; height:58px; border-radius:15px; object-fit:cover; background:#111318; border:1px solid var(--line) }}
.league-fallback {{ display:grid; place-items:center; color:var(--accent); font-size:22px; font-weight:900 }}
.tags {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:7px }}
.tag {{ font-size:11px; padding:4px 7px; border-radius:999px; background:#252a34 }}
.date-block {{ text-align:right; min-width:92px }}
.date-block strong {{ display:block; font-size:17px }}
.empty {{ padding:45px 20px; text-align:center; color:var(--muted); border:1px dashed var(--line); border-radius:18px }}
dialog {{ width:min(620px,calc(100% - 24px)); border:1px solid var(--line); border-radius:22px; color:var(--text); background:var(--panel); padding:0 }}
dialog::backdrop {{ background:rgba(0,0,0,.7) }}
.dialog-body {{ padding:22px }}
.dialog-head {{ display:flex; justify-content:space-between; gap:14px }}
.dialog-title {{ display:flex; gap:14px; align-items:center }}
.close {{ border:0; background:transparent; color:var(--muted); font-size:26px; cursor:pointer }}
.detail-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:13px; margin:20px 0 }}
.detail {{ background:#111318; border-radius:12px; padding:12px }}
.detail small {{ color:var(--muted); display:block; margin-bottom:3px }}
.actions {{ display:flex; flex-wrap:wrap; gap:8px }}
.cancelled-banner {{ padding:9px 12px; background:rgba(239,83,80,.15); border:1px solid rgba(239,83,80,.4); border-radius:10px; margin-bottom:14px }}
[hidden] {{ display:none!important }}
@media(max-width:760px) {{
  .controls {{ grid-template-columns:1fr }}
  .filters {{ grid-template-columns:1fr }}
  .calendar {{ display:grid; grid-template-columns:1fr; border:0; background:transparent }}
  .weekday,.outside {{ display:none }}
  .day {{ min-height:0; border:1px solid var(--line); border-radius:14px; margin-bottom:9px }}
  .event-card {{ grid-template-columns:52px 1fr }}
  .league-logo,.league-fallback {{ width:48px; height:48px; border-radius:12px }}
  .date-block {{ grid-column:2; text-align:left }}
  .detail-grid {{ grid-template-columns:1fr }}
}}
</style>
</head>
<body>
<main class="shell">
<header><div class="brandmark">P</div><div><h1>PokÈvent</h1><p class="subtitle">Pokémon events around {home}</p></div></header>
<section class="controls">
  <div class="switcher"><button id="calendarMode" class="active">Calendar</button><button id="listMode">List</button></div>
  <div class="filters">
    <select id="gameFilter"><option value="">All games</option></select>
    <select id="typeFilter"><option value="">All event types</option></select>
    <select id="leagueFilter"><option value="">All Leagues</option></select>
  </div>
</section>
<section id="calendarSection">
  <div class="toolbar"><h2 id="monthTitle"></h2><div class="month-nav"><button class="ghost" id="prevMonth">←</button><button class="ghost" id="todayMonth">Today</button><button class="ghost" id="nextMonth">→</button></div></div>
  <div class="calendar" id="calendar"></div>
</section>
<section id="listSection" hidden>
  <div class="toolbar"><h2>Upcoming events</h2><span class="meta" id="resultCount"></span></div>
  <div class="list" id="eventList"></div>
</section>
</main>
<dialog id="eventDialog"><div class="dialog-body" id="eventDetail"></div></dialog>
<script>
var state={{events:[],filtered:[],mode:"calendar",month:new Date(new Date().getFullYear(),new Date().getMonth(),1)}};
var gameLabels={{tcg:"Pokémon TCG",vgc:"Pokémon VGC",go:"Pokémon GO"}};
function byId(id){{return document.getElementById(id)}}
var els={{calendarMode:byId("calendarMode"),listMode:byId("listMode"),gameFilter:byId("gameFilter"),typeFilter:byId("typeFilter"),leagueFilter:byId("leagueFilter"),calendarSection:byId("calendarSection"),listSection:byId("listSection"),calendar:byId("calendar"),eventList:byId("eventList"),monthTitle:byId("monthTitle"),resultCount:byId("resultCount"),prevMonth:byId("prevMonth"),nextMonth:byId("nextMonth"),todayMonth:byId("todayMonth"),eventDialog:byId("eventDialog"),eventDetail:byId("eventDetail")}};
function esc(v){{return String(v==null?"":v).replace(/[&<>"']/g,function(c){{return {{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c]}})}}
function gameLabel(v){{return gameLabels[String(v||"").toLowerCase()]||String(v||"Pokémon")}}
function dateOnly(v){{return new Intl.DateTimeFormat(undefined,{{weekday:"short",day:"numeric",month:"short"}}).format(new Date(v))}}
function dateFull(v){{return new Intl.DateTimeFormat(undefined,{{weekday:"long",day:"numeric",month:"long",year:"numeric",hour:"2-digit",minute:"2-digit"}}).format(new Date(v))}}
function logo(e){{return e.league_logo?'<img class="league-logo" src="'+esc(e.league_logo)+'" alt="">':'<div class="league-fallback">P</div>'}}
function addOption(el,value,label){{var o=document.createElement("option");o.value=value;o.textContent=label;el.appendChild(o)}}
function populateFilters(){{
  Array.from(new Set(state.events.map(function(e){{return e.game}}).filter(Boolean))).sort().forEach(function(v){{addOption(els.gameFilter,v,gameLabel(v))}});
  Array.from(new Set(state.events.map(function(e){{return e.event_type}}).filter(Boolean))).sort().forEach(function(v){{addOption(els.typeFilter,v,v)}});
  var leagues={{}};state.events.forEach(function(e){{if(e.league_id)leagues[e.league_id]=e.league_name||e.league_id}});
  Object.keys(leagues).sort(function(a,b){{return leagues[a].localeCompare(leagues[b])}}).forEach(function(id){{addOption(els.leagueFilter,id,leagues[id])}});
}}
function applyFilters(){{
  var g=els.gameFilter.value,t=els.typeFilter.value,l=els.leagueFilter.value;
  state.filtered=state.events.filter(function(e){{return(!g||e.game===g)&&(!t||e.event_type===t)&&(!l||e.league_id===l)}});
  render();
}}
function bindEvents(root){{root.querySelectorAll("[data-event]").forEach(function(n){{n.addEventListener("click",function(){{openEvent(n.dataset.event)}})}})}}
function eventPill(e){{
  return '<button class="event-pill'+(e.status==="cancelled"?" cancelled":"")+'" data-event="'+esc(e.id)+'"><strong>'+esc(e.title)+'</strong><br><span class="meta">'+esc(gameLabel(e.game))+'</span></button>';
}}
function renderCalendar(){{
  var y=state.month.getFullYear(),m=state.month.getMonth(),first=new Date(y,m,1),offset=(first.getDay()+6)%7,start=new Date(y,m,1-offset);
  els.monthTitle.textContent=new Intl.DateTimeFormat(undefined,{{month:"long",year:"numeric"}}).format(state.month);
  var h=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(function(d){{return '<div class="weekday">'+d+'</div>'}}).join("");
  for(var i=0;i<42;i++){{var d=new Date(start);d.setDate(start.getDate()+i);var key=d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");var rows=state.filtered.filter(function(e){{return e.starts_at.slice(0,10)===key}});h+='<div class="day'+(d.getMonth()!==m?" outside":"")+'"><div class="day-number">'+d.getDate()+'</div>'+rows.map(eventPill).join("")+'</div>'}}
  els.calendar.innerHTML=h;bindEvents(els.calendar);
}}
function renderList(){{
  els.resultCount.textContent=state.filtered.length+" event"+(state.filtered.length===1?"":"s");
  if(!state.filtered.length){{els.eventList.innerHTML='<div class="empty">No events match these filters.</div>';return}}
  var h="";
  state.filtered.forEach(function(e){{h+='<article class="event-card" data-event="'+esc(e.id)+'">'+logo(e)+'<div><h3>'+(e.status==="cancelled"?"❌ ":"")+esc(e.title)+'</h3><div class="meta">'+esc(e.league_name||"Play! Pokémon")+' · '+esc(e.venue_name||e.city||"Venue TBC")+'</div><div class="tags"><span class="tag">'+esc(gameLabel(e.game))+'</span><span class="tag">'+esc(e.event_type||"Event")+'</span></div></div><div class="date-block"><strong>'+esc(dateOnly(e.starts_at))+'</strong><span class="meta">'+esc(new Date(e.starts_at).toLocaleTimeString([],{{hour:"2-digit",minute:"2-digit"}}))+'</span></div></article>'}});
  els.eventList.innerHTML=h;bindEvents(els.eventList);
}}
function render(){{renderCalendar();renderList();els.calendarSection.hidden=state.mode!=="calendar";els.listSection.hidden=state.mode!=="list";els.calendarMode.classList.toggle("active",state.mode==="calendar");els.listMode.classList.toggle("active",state.mode==="list")}}
function openEvent(id){{
  var e=state.events.find(function(row){{return row.id===id}});if(!e)return;
  var locationText=[e.venue_name,e.address,e.city,e.postcode].filter(Boolean).join(", ");
  var directions=locationText?"https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(locationText):null;
  var official=e.source_url?'<a class="primary" target="_blank" rel="noopener" href="'+esc(e.source_url)+'">View on Pokémon</a>':"";
  var registration=e.registration_url&&e.status!=="cancelled"?'<a class="ghost" target="_blank" rel="noopener" href="'+esc(e.registration_url)+'">Register</a>':"";
  var h='<div class="dialog-head"><div class="dialog-title">'+logo(e)+'<div><div class="meta">'+esc(e.league_name||"Play! Pokémon")+'</div><h2>'+esc(e.title)+'</h2></div></div><button class="close">×</button></div>';
  if(e.status==="cancelled")h+='<div class="cancelled-banner"><strong>❌ This event is cancelled.</strong></div>';
  h+='<div class="detail-grid"><div class="detail"><small>When</small><strong>'+esc(dateFull(e.starts_at))+'</strong></div><div class="detail"><small>Event</small><strong>'+esc(gameLabel(e.game))+' · '+esc(e.event_type||"Event")+'</strong></div><div class="detail"><small>Venue</small><strong>'+esc(e.venue_name||"TBC")+'</strong><div class="meta">'+esc([e.address,e.city,e.postcode].filter(Boolean).join(", "))+'</div></div><div class="detail"><small>League</small><strong>'+esc(e.league_name||"Play! Pokémon")+'</strong></div></div><div class="actions">'+official+registration+'<a class="ghost" href="/events/'+encodeURIComponent(e.id)+'.ics">Add to calendar</a>'+(directions?'<a class="ghost" target="_blank" rel="noopener" href="'+directions+'">Directions</a>':"")+'<button class="ghost" id="shareEvent">Share</button></div>';
  els.eventDetail.innerHTML=h;
  els.eventDetail.querySelector(".close").addEventListener("click",function(){{els.eventDialog.close()}});
  els.eventDetail.querySelector("#shareEvent").addEventListener("click",async function(){{var u=new URL(window.location.href);u.hash="event="+e.id;if(navigator.share)await navigator.share({{title:e.title,url:u.toString()}});else if(navigator.clipboard)await navigator.clipboard.writeText(u.toString())}});
  history.replaceState(null,"","#event="+encodeURIComponent(e.id));els.eventDialog.showModal();
}}
async function load(){{
  var response=await fetch("/api/events?limit=500&include_cancelled=true");state.events=await response.json();populateFilters();applyFilters();
  var match=location.hash.match(/^#event=(.+)$/);if(match)openEvent(decodeURIComponent(match[1]));
}}
els.calendarMode.addEventListener("click",function(){{state.mode="calendar";render()}});
els.listMode.addEventListener("click",function(){{state.mode="list";render()}});
[els.gameFilter,els.typeFilter,els.leagueFilter].forEach(function(el){{el.addEventListener("change",applyFilters)}});
els.prevMonth.addEventListener("click",function(){{state.month=new Date(state.month.getFullYear(),state.month.getMonth()-1,1);renderCalendar()}});
els.nextMonth.addEventListener("click",function(){{state.month=new Date(state.month.getFullYear(),state.month.getMonth()+1,1);renderCalendar()}});
els.todayMonth.addEventListener("click",function(){{var d=new Date();state.month=new Date(d.getFullYear(),d.getMonth(),1);renderCalendar()}});
els.eventDialog.addEventListener("close",function(){{history.replaceState(null,"",location.pathname+location.search)}});
load();
</script>
</body>
</html>"""
