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

function seite({transport, gespeichert=null}={}) {
  const elemente=new Map(); const ereignisse=new Map(); const timer=new Map(); const aufrufe=[]; let id=0, callback;
  const element=id => {
    if (!elemente.has(id)) elemente.set(id,{disabled:false, hidden:false, textContent:'', addEventListener:(art,fn)=>ereignisse.set(id+':'+art,fn)});
    return elemente.get(id);
  };
  const kontext=vm.createContext({document:{getElementById:element,createElement:()=>({}),head:{appendChild:()=>{}}},
    window:{location:{origin:'https://werkstatt.invalid'}, addEventListener:(art,fn)=>ereignisse.set(art,fn)},
    sessionStorage:{getItem:()=>gespeichert,setItem:(schluessel,wert)=>{gespeichert=wert;}},
    setTimeout:(fn,ms)=>{timer.set(++id,{fn,ms});return id;},clearTimeout:id=>timer.delete(id),
    fetch:async(url,init)=>{const daten=JSON.parse(init.body);aufrufe.push([url,daten]);return transport ? transport(url,daten) : {ok:true,json:async()=>({kennung:'k'.repeat(43),meldung:'Synthetisch',zustand:'offen'})};},
    FB:{init:()=>{},login:(cb,optionen)=>{callback=cb;aufrufe.push(['FB.login',optionen]);}}
  });
  kontext.window.FB=kontext.FB;vm.runInContext(quelle,kontext);
  kontext.starteAnschlussSeite({workshopId:'synthetisch',origin:'https://werkstatt.invalid',appId:'111',configId:'222',version:'v26.0'});
  return {kontext,element,ereignisse,timer,aufrufe,callback:antwort=>callback(antwort),alterCallback:()=>callback};
}
const abwarten=()=>new Promise(resolve=>setImmediate(resolve));

test('Browser-Erfolg allein reicht nicht; Code und Session-Ereignis ergeben genau einen Serverabschluss', async()=>{
  const s=seite();s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
  const optionen=s.aufrufe.find(a=>a[0]==='FB.login')[1];
  assert.equal(optionen.extras.featureType,'whatsapp_business_app_onboarding');
  assert.equal(optionen.extras.sessionInfoVersion,'3');assert.equal(optionen.extras.version,undefined);
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

const antwort = (daten, ok=true) => ({ok, json:async()=>daten});
for (const neustart of [false,true]) {
  test(`Abbruch nach Commit zeigt den tatsächlichen Abschluss; neuer Versuch: ${neustart}`, async()=>{
    let alterAbschluss, alterAbbruch, nummer=0, abschluesse=0;
    const meldung='Zugang autorisiert. Automatik bleibt bis zum Echo- und Synchronisierungsschutz gesperrt.';
    const s=seite({transport:async url=>{
      if (url.endsWith('/start')) return antwort({kennung:String(++nummer).repeat(43),meldung:'Bereit'});
      if (url.endsWith('/abschluss') && ++abschluesse === 1)
        return new Promise(resolve=>{alterAbschluss=()=>resolve(antwort({zustand:'abgeschlossen',meldung:'Verspätete Abschlussantwort'}));});
      if (url.endsWith('/abbruch')) {
        const ergebnis={zustand:'abgeschlossen',meldung,fortsetzbar:false,coexistence_bereit:false};
        if (neustart) return new Promise(resolve=>{alterAbbruch=()=>resolve(antwort(ergebnis));});
        return antwort(ergebnis);
      }
      return antwort({zustand:'abgeschlossen',meldung});
    }});
    s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
    s.callback({authResponse:{code:'synthetisch-alt'}});
    s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
    assert.equal(s.element('abbruch').hidden,false);
    const abbruch=s.ereignisse.get('abbruch:click')();
    if (neustart) {
      s.ereignisse.get('start:click')();await abwarten();s.ereignisse.get('start:click')();
      const aktuellerText=s.element('fortschritt').textContent;
      alterAbbruch();await abbruch;alterAbschluss();await abwarten();
      assert.equal(s.element('fortschritt').textContent,aktuellerText);
      assert.equal(s.element('start').disabled,true);
      s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});
      s.callback({authResponse:{code:'synthetisch-neu'}});await abwarten();
      s.callback({authResponse:{code:'synthetisch-neu'}});await abwarten();
      assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/abschluss') && a[1].kennung==='2'.repeat(43)).length,1);
    } else {
      await abbruch;
      assert.equal(s.element('fortschritt').textContent,meldung);
      alterAbschluss();await abwarten();
    }
    assert.equal(s.element('fortschritt').textContent,meldung);
    assert.equal(s.element('fortsetzen').hidden,true);
    assert.equal(s.element('abbruch').hidden,true);
  });
}

for (const aktion of ['abschluss','abbruch','status','fortsetzen','start']) {
  for (const erfolg of [true,false]) {
    test(`Verspätete ${aktion}-Antwort (${erfolg ? 'Erfolg' : 'Fehler'}) verändert keinen neuen Popup-Versuch`, async()=>{
      let freigeben, angehalten=false, nummer=0;
      const s=seite({transport:async(url)=>{
        if (url.endsWith('/'+aktion) && !angehalten) {
          angehalten=true;
          return new Promise(resolve=>{freigeben=()=>resolve(antwort({kennung:'alt'.repeat(14)+'a',
            meldung:'Veraltete Antwort',detail:'Veralteter Fehler',fortsetzbar:true},erfolg));});
        }
        if (url.endsWith('/start')) return antwort({kennung:String(++nummer).repeat(43),meldung:'Bereit'});
        if (url.endsWith('/status')) return antwort({meldung:'Teilzustand',fortsetzbar:true});
        return antwort({meldung:'Aktuelle Antwort',zustand:'abgeschlossen'});
      }});
      s.kontext.window.fbAsyncInit();await abwarten();
      let alterTimer, alterCallback;
      if (aktion !== 'start') {
        s.ereignisse.get('start:click')();
        alterTimer=[...s.timer.values()].find(t=>t.ms===9*60*1000).fn;
        alterCallback=s.alterCallback();
      }
      if (aktion === 'abschluss') {
        s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});
        s.callback({authResponse:{code:'synthetisch-alt'}});
      } else if (aktion === 'status') {
        s.ereignisse.get('status:click')();
      } else if (aktion === 'fortsetzen') {
        await s.ereignisse.get('status:click')();
        s.ereignisse.get('fortsetzen:click')();
      }
      s.ereignisse.get('abbruch:click')();await abwarten();
      s.ereignisse.get('start:click')();await abwarten();
      s.ereignisse.get('start:click')();
      const neuerText=s.element('fortschritt').textContent;
      assert.equal(s.element('start').disabled,true);
      assert.equal(typeof freigeben,'function');
      freigeben();await abwarten();
      if (alterTimer) alterTimer();
      if (alterCallback) alterCallback({authResponse:{code:'synthetisch-verspaetet'}});
      await abwarten();
      assert.equal(s.element('start').disabled,true);
      assert.equal(s.element('fortschritt').textContent,neuerText);
      assert.equal(s.element('fortsetzen').hidden,true);
      // Auch die umgekehrte Reihenfolge bleibt möglich: zuerst Code, dann Session-Ereignis.
      s.callback({authResponse:{code:'synthetisch-neu'}});
      s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
      s.callback({authResponse:{code:'synthetisch-neu'}});
      s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
      const abschluesse=s.aufrufe.filter(a=>a[0].endsWith('/abschluss') && a[1].code==='synthetisch-neu');
      assert.equal(abschluesse.length,1);
      assert.equal(abschluesse[0][1].kennung,String(nummer).repeat(43));
      assert.equal(s.element('fortschritt').textContent,'Aktuelle Antwort');
    });
  }
}

test('Verspäteter Status desselben Laufs überschreibt keinen abgeschlossenen Anschluss', async()=>{
  let freigeben;
  const s=seite({transport:async url=>{
    if (url.endsWith('/status')) return new Promise(resolve=>{freigeben=()=>resolve(antwort({meldung:'Alter Status'}));});
    return antwort({kennung:'k'.repeat(43),meldung:'Aktueller Abschluss'});
  }});
  s.kontext.window.fbAsyncInit();await abwarten();s.ereignisse.get('start:click')();
  s.ereignisse.get('status:click')();
  s.callback({authResponse:{code:'synthetisch'}});
  s.ereignisse.get('message')({origin:'https://www.facebook.com',data:daten});await abwarten();
  freigeben();await abwarten();
  assert.equal(s.element('fortschritt').textContent,'Aktueller Abschluss');
});

test('Veralteter initialer Statusfehler startet keine zusätzliche Vorbereitung', async()=>{
  let ablehnen;
  const s=seite({gespeichert:'a'.repeat(43),transport:async url=>{
    if (url.endsWith('/status')) return new Promise((resolve,reject)=>{ablehnen=()=>reject(new Error('Synthetischer Ausfall'));});
    return antwort({kennung:'b'.repeat(43),meldung:'Aktuell'});
  }});
  s.kontext.window.fbAsyncInit();await abwarten();
  await s.ereignisse.get('abbruch:click')();
  s.ereignisse.get('start:click')();await abwarten();s.ereignisse.get('start:click')();
  const text=s.element('fortschritt').textContent;
  ablehnen();await abwarten();
  assert.equal(s.element('fortschritt').textContent,text);
  assert.equal(s.element('start').disabled,true);
  assert.equal(s.aufrufe.filter(a=>a[0].endsWith('/start')).length,1);
});

test('Erneute Statusprüfung während Wiederherstellung sperrt keinen Neustart', async()=>{
  const antworten=[];
  const s=seite({gespeichert:'a'.repeat(43),transport:async url=>{
    if (url.endsWith('/status')) return new Promise(resolve=>antworten.push(resolve));
    return antwort({kennung:'b'.repeat(43),meldung:'Aktuell'});
  }});
  s.kontext.window.fbAsyncInit();await abwarten();
  s.ereignisse.get('status:click')();
  antworten[1](antwort({meldung:'Aktueller Status'}));await abwarten();
  antworten[0](antwort({meldung:'Alter Status'}));await abwarten();
  assert.equal(s.element('start').disabled,false);
  assert.equal(s.element('fortschritt').textContent,'Aktueller Status');
  s.ereignisse.get('start:click')();await abwarten();s.ereignisse.get('start:click')();
  assert.equal(s.aufrufe.filter(a=>a[0]==='FB.login').length,1);
});

test('Späte SDK-Initialisierung überschreibt keine bereits laufende Wiederaufnahme', async()=>{
  let freigeben;
  const s=seite({gespeichert:'a'.repeat(43),transport:async url=>{
    if (url.endsWith('/fortsetzen')) return new Promise(resolve=>{freigeben=()=>resolve(antwort({meldung:'Abgeschlossen'}));});
    return antwort({kennung:'b'.repeat(43),meldung:'Teilzustand',fortsetzbar:true});
  }});
  await s.ereignisse.get('status:click')();s.ereignisse.get('fortsetzen:click')();
  const text=s.element('fortschritt').textContent;
  s.kontext.window.fbAsyncInit();await abwarten();
  assert.equal(s.element('fortschritt').textContent,text);
  freigeben();await abwarten();
  s.ereignisse.get('start:click')();await abwarten();s.ereignisse.get('start:click')();
  assert.equal(s.aufrufe.filter(a=>a[0]==='FB.login').length,1);
});
