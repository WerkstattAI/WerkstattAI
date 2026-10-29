// Tatsächliche Seiten aus der Gesamtkette, tatsächliche CSP und abgefangener Transport.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.WERKSTATTAI_PRUEFPLAYWRIGHT);
const ordner = process.env.WERKSTATTAI_PRUEFAUSGABE;
assert(ordner && process.env.WERKSTATTAI_PRUEFCHROME, 'Eigenen Ausgabeordner und Chrome angeben.');
fs.mkdirSync(ordner, {recursive:true});
const quelle = spawnSync(process.env.WERKSTATTAI_PRUEFPYTHON || 'python', ['-c', `
import json,sys
sys.path.insert(0,'tests')
from test_m2_gesamtabnahme import SQLiteAbnahme
seiten={}
for methode in ('test_zwei_werkstaetten_vom_signup_bis_zum_offboarding','test_null_prozent_ablehnung_und_fruehe_rueckmeldung_nach_signup'):
    t=SQLiteAbnahme()
    try:
        t.setUp()
        original=t.seite
        def sichern(name,w,pfad='/dashboard/whatsapp/verbinden'):
            original(name,w,pfad)
            if name in ('abgeschlossen','widerrufen'):
                original('einstellungen-'+name,w,'/dashboard/settings')
        t.seite=sichern
        getattr(t,methode)()
        seiten.update(t.seiten)
    finally:
        t.doCleanups()
print(json.dumps(seiten))
`], {cwd:path.resolve(__dirname,'..'), encoding:'utf8', env:{...process.env, DATABASE_URL:'',
    APP_ENV:'test', AUTH_SECRET:'synthetischer-browser-abnahmeschluessel', PYTHONUTF8:'1', PYTHONDONTWRITEBYTECODE:'1'}});
assert.equal(quelle.status,0,quelle.stderr);
const seiten=JSON.parse(quelle.stdout);
(async()=>{
  const browser=await chromium.launch({headless:true, executablePath:process.env.WERKSTATTAI_PRUEFCHROME});
  try {
    const context=await browser.newContext({serviceWorkers:'block'});
    let aktuell='offen', statusaufrufe=0;
    await context.route('**/*', route=>{
      const u=new URL(route.request().url());
      if(u.origin==='https://testserver' && route.request().resourceType()==='document')
        return route.fulfill({status:200,contentType:'text/html',headers:{'content-security-policy':seiten[aktuell].csp},body:seiten[aktuell].html});
      if(u.href==='https://testserver/dashboard/whatsapp/synchronisierung/status') {
        statusaufrufe++;
        assert.equal(route.request().headers().origin,'https://testserver');
        return route.fulfill({status:200,json:{autorisiert:true,technisch_bereit:false,schritte:[
          {art:'history',zustand:'unklar',meldung:'Ergebnis unklar. Kein erneuter Start.',fortschritt:0,startbar:false}]}});
      }
      return route.abort();
    });
    const page=await context.newPage();
    const belege=[];
    for(const breite of [1200,390]) {
      await page.setViewportSize({width:breite,height:900});
      for(const name of ['offen','laufend','abgeschlossen','nicht_geteilt','pruefung','widerrufen','einstellungen-abgeschlossen','einstellungen-widerrufen','telefon']) {
        aktuell=name;
        const pfad=name.startsWith('einstellungen')?'/dashboard/settings':name==='telefon'?'/dashboard/whatsapp':'/dashboard/whatsapp/verbinden';
        await page.goto('https://testserver'+pfad);
        if(name.startsWith('einstellungen')) {
          assert.match(await page.locator('body').innerText(),name.endsWith('widerrufen')?/Autorisierung: Widerrufen/:/Autorisierung: Bestätigt/);
        } else if(name==='telefon') {
          const text=await page.locator('#messageThread').innerText();
          assert.match(text,/Importierter Verlauf/);
          assert.match(text,/Antwort aus der Business-App/);
          assert.match(await page.locator('body').innerText(),/Assistent übernimmt/);
        } else {
          const text=await page.locator('#sync-status').innerText();
          if(name==='abgeschlossen')assert.match(text,/Technische Synchronisierungsbedingungen erfüllt/);
          if(name==='nicht_geteilt')assert.match(text,/nicht geteilt/);
          if(name==='pruefung')assert.match(text,/geprüft/);
          if(name!=='widerrufen')assert.match(text,/Betriebliche Automatikfreigabe bleibt geschlossen/);
        }
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,name+' ohne horizontalen Überlauf');
        await page.screenshot({path:path.join(ordner,name+'-'+breite+'.png'),fullPage:true});
        if(name==='telefon') {
          await page.locator('#messageThread').getByText('Antwort aus der Business-App',{exact:true}).scrollIntoViewIfNeeded();
          await page.screenshot({path:path.join(ordner,'telefon-ausschnitt-'+breite+'.png')});
        }
        belege.push({seite:name,breite});
      }
    }
    aktuell='pruefung';
    await page.goto('https://testserver/dashboard/whatsapp/verbinden');
    await page.locator('#sync-pruefen').click();
    await page.getByText('Verlauf: Ergebnis unklar. Kein erneuter Start. Fortschritt: 0 %.').waitFor();
    assert.equal(statusaufrufe,1);
    const ergebnis={datum:new Date().toISOString(),browser:await browser.version(),belege,csp:true,origin:true,
      statusaktion:true,echter_meta_transport:false,sdk_absichtlich_gesperrt:true};
    fs.writeFileSync(path.join(ordner,'browser-ergebnis.json'),JSON.stringify(ergebnis,null,2));
    console.log(JSON.stringify(ergebnis));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
