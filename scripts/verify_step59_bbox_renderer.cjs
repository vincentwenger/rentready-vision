// Step 59 renderer contract checks. This does not replace a browser/PDF check.
// Usage: node scripts/verify_step59_bbox_renderer.cjs web/index.html
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.slice(html.indexOf('async function renderReportIssue'), html.indexOf('async function renderIssues'));
assert.ok(source.startsWith('async function renderReportIssue'));
class Element {
  constructor(tag, namespace) { this.tagName=tag; this.namespaceURI=namespace; this.children=[]; this.attrs={}; this.listeners={}; this.style={}; this.className=''; this.classList={add:c=>{this.className=c}}; }
  append(...items) { this.children.push(...items); }
  setAttribute(k,v) { this.attrs[k]=String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k,v) { this.listeners[k]=v; }
  querySelector(selector) { for(const child of this.children){ if(child.className===selector.slice(1))return child; const found=child.querySelector?.(selector); if(found)return found; } return null; }
}
async function render(bbox,width=1080,height=1920,cached=false) {
  const requests=[];
  const created=[];
  const context={Number,String,Math,document:{createElement:tag=>{const el=new Element(tag);if(tag==='img'){el.complete=cached;el.naturalWidth=cached?width:0;el.naturalHeight=cached?height:0;}created.push(el);return el;},createElementNS:(ns,tag)=>new Element(tag,ns),createTextNode:text=>({text})},api:async p=>{requests.push(p);return {url:'offline-frame.jpeg'}},formatTimestamp:()=> '00:00',confidenceBadge:()=>new Element('span'),openVideoAt:()=>{throw Error('Unexpected video request')}};
  vm.createContext(context);
  vm.runInContext(source+'\nthis.render=renderReportIssue;',context);
  const card=await context.render('offline-test',{bbox,representative_frame_index:4,title:'Test',confidence:.85});
  assert.deepEqual(requests,['/inspections/offline-test/frames/4/url']);
  return {card,img:created.find(x=>x.tagName==='img'),svg:card.querySelector('.report-evidence-bbox')};
}
(async()=>{
  let checks=0;
  for(const [width,height] of [[1080,1920],[1088,1920],[1920,1080]]) {
    const bbox={x:.2,y:.3,width:.4,height:.2};
    for(const cached of [false,true]) {
      const {img,svg}=await render(bbox,width,height,cached);
      assert.equal(svg.namespaceURI,'http://www.w3.org/2000/svg');
      assert.equal(svg.attrs.preserveAspectRatio,'xMidYMid meet');
      assert.equal(svg.attrs['aria-hidden'],'true');
      if(!cached){assert.ok('hidden' in svg.attrs);img.naturalWidth=width;img.naturalHeight=height;img.listeners.load();}
      assert.ok(!('hidden' in svg.attrs));
      assert.equal(svg.attrs.viewBox,`0 0 ${width} ${height}`);
      const rect=svg.children[0];
      assert.deepEqual(rect.attrs,{x:String(.2*width),y:String(.3*height),width:String(.4*width),height:String(.2*height)});
      // The browser can change the image element's size without changing source coordinates.
      // Confirm there are no screen dimensions stored on the source-coordinate rectangle.
      assert.deepEqual(svg.style,{});
      for(const [boxWidth,boxHeight] of [[872,460],[653,460],[270,460],[1100,300]]) {
        const view=svg.attrs.viewBox.split(' ').map(Number);
        const scale=Math.min(boxWidth/view[2],boxHeight/view[3]);
        const paintedW=view[2]*scale,paintedH=view[3]*scale;
        assert.ok(Math.abs(Number(rect.attrs.x)*scale/paintedW-bbox.x)<1e-12);
        assert.ok(Math.abs(Number(rect.attrs.y)*scale/paintedH-bbox.y)<1e-12);
        assert.ok(Math.abs(Number(rect.attrs.width)*scale/paintedW-bbox.width)<1e-12);
        assert.ok(Math.abs(Number(rect.attrs.height)*scale/paintedH-bbox.height)<1e-12);
      }
      img.listeners.error();assert.ok('hidden' in svg.attrs);
      img.listeners.load();assert.ok(!('hidden' in svg.attrs));
      checks++;
    }
  }
  for(const bbox of [null,{}, {x:NaN,y:.1,width:.1,height:.1},{x:Infinity,y:.1,width:.1,height:.1},{x:'0.1',y:.1,width:.1,height:.1},{x:-.1,y:.1,width:.1,height:.1},{x:.1,y:-.1,width:.1,height:.1},{x:.1,y:.1,width:0,height:.1},{x:.1,y:.1,width:.1,height:0},{x:0,y:0,width:1,height:1},{x:.95,y:.1,width:.2,height:.1},{x:.1,y:.95,width:.1,height:.2}]) {
    const {svg}=await render(bbox);assert.equal(svg,null);checks++;
  }
  const {svg}=await render({x:.8,y:.8,width:.2,height:.2},1080,1920,true);assert.ok(svg);checks++;
  console.log(`PASS: ${checks} renderer cases; portrait/landscape, source geometry, cached/load/error states, and invalid-box guards.`);
  console.log('Browser/PDF visual verification remains required.');
})().catch(e=>{console.error(e);process.exitCode=1});
