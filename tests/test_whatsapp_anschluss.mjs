import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const quelle=readFileSync(new URL('../templates/_whatsapp_anschluss_script.html', import.meta.url),'utf8');
function umgebung() { const kontext=vm.createContext({}); vm.runInContext(quelle, kontext); return kontext; }
const daten={type:'WA_EMBEDDED_SIGNUP', version:3, event:'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING', data:{waba_id:'333'}};

test('Exakte Meta-Ursprünge und Session-Schema 3 bei Signup v4', () => {
  const kontext=umgebung();
  for (const origin of ['https://www.facebook.com','https://web.facebook.com']) {
    const ergebnis=kontext.pruefeMetaEreignis({origin,data:JSON.stringify(daten)});
    assert.equal(ergebnis.waba_id,'333'); assert.equal(ergebnis.phone_number_id,null);
  }
  for (const origin of ['null','http://www.facebook.com','https://www.facebook.com.evil.invalid','https://evilfacebook.com','https://www.facebook.com:444']) {
    assert.equal(kontext.pruefeMetaEreignis({origin,data:JSON.stringify(daten)}),null);
  }
});

test('Falscher Typ, falsche Version und manipulierte IDs werden verworfen', () => {
  const kontext=umgebung();
  for (const data of ['kein JSON',null,[],{...daten,type:'OTHER'},{...daten,version:4},{...daten,version:'3'},
    {...daten,data:[]},{...daten,data:{waba_id:333}},{...daten,data:{waba_id:'333/../me'}},
    {...daten,data:{waba_id:'333',phone_number_id:444}}]) {
    assert.equal(kontext.pruefeMetaEreignis({origin:'https://www.facebook.com',data}),null);
  }
});

test('Abbruch und fremde Flow-Erfolge aktivieren keine Coexistence', () => {
  const kontext=umgebung();
  for (const event of ['CANCEL','ERROR','FINISH','FINISH_ONLY_WABA']) {
    const ergebnis=kontext.pruefeMetaEreignis({origin:'https://www.facebook.com',data:{...daten,event}});
    assert.equal(ergebnis.abbruch,true);
    assert.equal(ergebnis.waba_id,undefined);
  }
});

function seite() {
  const elemente=new Map(); const ereignisse=new Map(); const timer=new Map(); const aufrufe=[]; let id=0, callback;
  const element=id => {
    if (!elemente.has(id)) elemente.set(id,{disabled:false, hidden:false, textContent:'', addEventListener:(art,fn)=>ereignisse.set(id+':'+art,fn)});
    return elemente.get(id);
  };
  const kontext=vm.createContext({document:{getElementById:element,createElement:()=>({}),head:{appendChild:()=>{}}},
    window:{location:{origin:'https://werkstatt.invalid'}, addEventListener:(art,fn)=>ereignisse.set(art,fn)},
    sessionStorage:{getItem:()=>null,setItem:()=>{}},
    setTimeout:(fn,ms)=>{timer.set(++id,{fn,ms});return id;},clearTimeout:id=>timer.delete(id),
    fetch:async(url,init)=>{aufrufe.push([url,JSON.parse(init.body)]);return {ok:true,json:async()=>({kennung:'k'.repeat(43),meldung:'Synthetisch',zustand:'offen'})};},
    FB:{init:()=>{},login:(cb,optionen)=>{callback=cb;aufrufe.push(['FB.login',optionen]);}}
  });
  kontext.window.FB=kontext.FB;vm.runInContext(quelle,kontext);
  kontext.starteAnschlussSeite({workshopId:'synthetisch',origin:'https://werkstatt.invalid',appId:'111',configId:'222',version:'v26.0'});
  return {kontext,element,ereignisse,timer,aufrufe,callback:antwort=>callback(antwort)};
}
const abwarten=()=>new Promise(resolve=>setImmediate(resolve));

test('Browser-Erfolg allein reicht nicht; Code und Session-Ereignis ergeben genau einen Serverabschluss', async()=>{
  const s=seite();s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
  const optionen=s.aufrufe.find(a=>a[0]==='FB.login')[1];
  assert.equal(optionen.extras.featureType,'whatsapp_business_app_onboarding');
  assert.equal(optionen.extras.sessionInfoVersion,undefined);assert.equal(optionen.extras.version,undefined);
  s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,0);
  s.callback({authResponse:{code:'synthetisch'}});await abwarten();
  s.callback({authResponse:{code:'synthetisch'}});await abwarten();
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,1);
});

test('Geschlossenes Popup erzeugt keinen Abschluss', async()=>{
  const s=seite();s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
  s.callback({});await abwarten();
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,0);
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abbruch')).length,1);
  assert.equal(s.element('start').disabled,false);
});

test('SDK-Fehler und fehlende SDK-Antwort bleiben sichtbar und aktivieren nichts', async()=>{
  const s=seite();
  [...s.timer.values()].find(t=>t.ms===15000).fn();
  assert.match(s.element('fortschritt').textContent,/lädt nicht/);
  s.kontext.window.fbAsyncInit();await abwarten();
  s.kontext.FB.login=()=>{throw new Error('Synthetischer SDK-Fehler');};
  s.ereignisse.get('start:click')();await abwarten();
  assert.match(s.element('fortschritt').textContent,/nicht geöffnet/);
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,0);
});

test('Code vor Session-Ereignis und Popup-Zeitlimit bleiben kontrolliert', async()=>{
  const s=seite();s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
  s.callback({authResponse:{code:'synthetisch'}});await abwarten();
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,0);
  [...s.timer.values()].find(t=>t.ms===20000).fn();await abwarten();
  s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss')).length,0);
});
