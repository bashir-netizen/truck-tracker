"""In-dashboard track player — a self-contained deck.gl TripsLayer animation.

Renders ONE trip's GPS path with play / pause / scrub / speed, entirely
client-side (smooth; no Streamlit reruns per frame). deck.gl loads from a CDN and
the basemap is token-free Carto raster tiles, so there's no Python dependency and
no Mapbox key. Embed the returned HTML with st.components.v1.html(html, height=...).

This is the "hybrid" half of the Map: the native st.pydeck_chart handles the
multi-trip map + click selection; this handles smooth playback of the selected
trip. (Wialon's own Track Player is an in-app modal with no URL state, so it can't
be deep-linked — this replaces that idea.)
"""

import html as _html
import json

DECK_CDN = "https://unpkg.com/deck.gl@9.0.0/dist.min.js"
CARTO_TILES = "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"

_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="__DECK__"></script>
<style>
 html,body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 #lbl{font-size:.85rem;color:#4a5260;padding:0 .2rem .35rem}
 #map{position:relative;width:100%;height:__MAPH__px;border-radius:12px;overflow:hidden;border:1px solid #e6e8ec;background:#f7f7f4}
 #bar{display:flex;align-items:center;gap:.45rem;padding:.55rem .1rem;flex-wrap:wrap}
 button{font:inherit;font-size:.9rem;border:1px solid #e6e8ec;background:#fff;border-radius:8px;padding:.25rem .55rem;cursor:pointer;color:#0e1116;line-height:1}
 button.on{background:#c43d2f;color:#fff;border-color:#c43d2f}
 #scrub{flex:1;min-width:140px;accent-color:#c43d2f}
 #clock{font-variant-numeric:tabular-nums;color:#4a5260;font-size:.82rem;min-width:104px;text-align:right}
 .spd{font-size:.8rem;padding:.2rem .45rem}
</style></head><body>
<div id="lbl">__LABEL__</div>
<div id="map"></div>
<div id="bar">
 <button id="restart" title="Restart">&#9198;</button>
 <button id="back" title="-10s">&#9194;</button>
 <button id="play" class="on" title="Play/pause">&#9208;</button>
 <button id="fwd" title="+10s">&#9193;</button>
 <button id="end" title="To end">&#9197;</button>
 <input id="scrub" type="range" min="0" max="__DUR__" value="0" step="1">
 <span id="clock">00:00 / 00:00</span>
 <span style="display:flex;gap:.25rem">
  <button class="spd" data-s="1">1&times;</button>
  <button class="spd" data-s="5">5&times;</button>
  <button class="spd on" data-s="25">25&times;</button>
  <button class="spd" data-s="100">100&times;</button>
 </span>
</div>
<script>
(function(){
 var mapEl=document.getElementById('map');
 if (typeof deck === "undefined"){mapEl.style.padding='1rem';mapEl.style.color='#c43d2f';
   mapEl.textContent='Could not load the map library (offline?). The track is still '+
   'visible on the multi-trip map above.'; return;}
 const DATA=__DATA__, CFG=__CFG__;
 const {DeckGL,TileLayer,BitmapLayer,PathLayer,TripsLayer,ScatterplotLayer}=deck;
 const path=DATA.path, times=DATA.times, dur=CFG.duration, rgb=CFG.rgb;
 let minLon=180,maxLon=-180,minLat=90,maxLat=-90;
 for(const c of path){minLon=Math.min(minLon,c[0]);maxLon=Math.max(maxLon,c[0]);
   minLat=Math.min(minLat,c[1]);maxLat=Math.max(maxLat,c[1]);}
 const cLon=(minLon+maxLon)/2,cLat=(minLat+maxLat)/2;
 const span=Math.max(maxLon-minLon,maxLat-minLat,0.01);
 const zoom=Math.max(4,Math.min(14,Math.log2(360/span)-1.2));
 let current=__FOCUS__,speed=25,playing=__AUTOPLAY__,last=null;
 function posAt(t){if(t<=0)return path[0];if(t>=times[times.length-1])return path[path.length-1];
   let i=1;while(i<times.length&&times[i]<t)i++;const a=path[i-1],b=path[i],t0=times[i-1],t1=times[i];
   const f=(t1===t0)?0:(t-t0)/(t1-t0);return [a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f];}
 function fmt(s){s=Math.max(0,Math.round(s));const m=Math.floor(s/60);
   return String(m).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
 const basemap=new TileLayer({id:'bm',data:CFG.tiles,minZoom:0,maxZoom:19,tileSize:256,
   renderSubLayers:p=>{const b=p.tile.boundingBox;
     return new BitmapLayer(p,{data:null,image:p.data,bounds:[b[0][0],b[0][1],b[1][0],b[1][1]]});}});
 const full=new PathLayer({id:'full',data:[{path:path}],getPath:d=>d.path,
   getColor:[rgb[0],rgb[1],rgb[2],55],getWidth:3,widthUnits:'pixels',widthMinPixels:2});
 function layers(){
   const trip=new TripsLayer({id:'trip',data:[{path:path,times:times}],getPath:d=>d.path,
     getTimestamps:d=>d.times,getColor:rgb,opacity:0.95,widthMinPixels:4,
     trailLength:Math.max(60,dur*0.3),currentTime:current});
   const head=new ScatterplotLayer({id:'head',data:[{p:posAt(current)}],getPosition:d=>d.p,
     getRadius:7,radiusUnits:'pixels',radiusMinPixels:5,getFillColor:rgb,stroked:true,
     getLineColor:[255,255,255],lineWidthMinPixels:2});
   return [basemap,full,trip,head];}
 const dk=new DeckGL({container:'map',initialViewState:{longitude:cLon,latitude:cLat,zoom:zoom},
   controller:true,layers:layers()});
 const $=id=>document.getElementById(id), playBtn=$('play');
 function render(){dk.setProps({layers:layers()});$('scrub').value=current;
   $('clock').textContent=fmt(current)+' / '+fmt(dur);}
 function setPlay(){playBtn.textContent=playing?'\\u23F8':'\\u25B6';playBtn.classList.toggle('on',playing);}
 function tick(ts){if(last==null)last=ts;const dt=(ts-last)/1000;last=ts;
   if(playing){current+=dt*speed;if(current>=dur){current=dur;playing=false;setPlay();}render();}
   requestAnimationFrame(tick);}
 playBtn.onclick=()=>{if(current>=dur)current=0;playing=!playing;last=null;setPlay();};
 $('restart').onclick=()=>{current=0;last=null;render();};
 $('end').onclick=()=>{current=dur;playing=false;setPlay();render();};
 $('back').onclick=()=>{current=Math.max(0,current-10);render();};
 $('fwd').onclick=()=>{current=Math.min(dur,current+10);render();};
 $('scrub').oninput=e=>{current=+e.target.value;playing=false;setPlay();render();};
 document.querySelectorAll('.spd').forEach(b=>b.onclick=()=>{speed=+b.dataset.s;
   document.querySelectorAll('.spd').forEach(x=>x.classList.remove('on'));b.classList.add('on');});
 setPlay();render();requestAnimationFrame(tick);
})();
</script></body></html>"""


def player_html(points, color=(196, 61, 47), label="", map_height=380,
                focus_s=0, autoplay=True):
    """Build the player HTML for one trip.

    points:   [[lon, lat, ts_epoch], ...] full-resolution GPS for the trip.
    color:    RGB tuple for the track.
    focus_s:  seconds from trip start to start the playhead at (e.g. an event
              moment). When > 0 we start paused there so the moment is visible.
    Returns an HTML string (or a small notice if the trip has no usable track).
    """
    pts = [p for p in (points or []) if p and p[0] is not None and p[1] is not None]
    if len(pts) < 2:
        return ("<div style='padding:1rem;color:#4a5260;font:14px -apple-system,"
                "sans-serif'>No GPS track recorded for this trip — nothing to play "
                "back.</div>")
    t0 = pts[0][2]
    data = {"path": [[p[0], p[1]] for p in pts],
            "times": [max(0, int(p[2] - t0)) for p in pts]}
    duration = data["times"][-1] or 1
    focus = max(0, min(int(focus_s), duration))
    if focus > 0:
        autoplay = False
    cfg = {"rgb": [int(c) for c in color], "duration": duration, "tiles": CARTO_TILES}
    return (_TEMPLATE
            .replace("__DECK__", DECK_CDN)
            .replace("__MAPH__", str(int(map_height)))
            .replace("__DUR__", str(int(duration)))
            .replace("__FOCUS__", str(focus))
            .replace("__AUTOPLAY__", "true" if autoplay else "false")
            .replace("__LABEL__", _html.escape(label or ""))
            .replace("__DATA__", json.dumps(data))
            .replace("__CFG__", json.dumps(cfg)))


def player_total_height(map_height=380):
    """Height to pass to st.components.v1.html (map + control bar + label)."""
    return int(map_height) + 92
