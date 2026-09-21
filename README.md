# Oikeustapausseuranta

Henkilökohtainen uutisvirta tietosuojaa, teknologiaa ja datasääntelyä koskevista
ratkaisuista. Python-skripti hakee aineiston 40 lähteestä, suodattaa sen
avainsanoilla ja kirjoittaa staattisen verkkosivun. GitHub Actions ajaa haun
arkisin aamulla ja GitHub Pages julkaisee sivun.

Ei palvelinta, ei tietokantaa, ei kuukausimaksua.

## Mitä missä tiedostossa on

| Tiedosto | Tehtävä |
|---|---|
| `sources.yaml` | Lähteet, avainsanat ja aiheluokat. Tätä muokkaat normaalisti. |
| `fetchers.py` | Lähdekohtaiset hakijat: RSS, SPARQL, HTML-listaus, OAI-PMH. |
| `filtering.py` | Avainsanasuodatus, aiheluokitus ja järjestys. |
| `render.py` | HTML-sivu, RSS-syöte ja JSON. |
| `main.py` | Käynnistys ja komentoriviargumentit. |
| `docs/` | Valmis sivu. GitHub Pages näyttää tämän kansion. |
| `state.json` | Muistaa nähdyt ratkaisut, jotta uudet saavat "uusi"-merkin. |

## Lähteet

Lähteet on ryhmitelty `sources.yaml`-tiedostossa samalla logiikalla kuin
Bird & Birdin kuukausittainen tietosuojauutiskirje, jotta sama aineisto tulee
katetuksi automaattisesti:

| Aihe | Lähteet |
|---|---|
| Kansallinen oikeuskäytäntö | KKO, KHO, markkinaoikeus, vakuutusoikeus, työtuomioistuin, tuomioistuinlaitoksen yhteinen ajankohtaissyöte (kaikki oikeusasteet tiedotteina), hallinto-oikeuksien ratkaisulista, hovioikeuksien ratkaisulista |
| EU | unionin tuomioistuin (SPARQL), curia-tiedotteet, komission digitaalinen strategia, Euroopan parlamentti |
| Säädösvalmistelu | Finlexin säädöskokoelma, Finlexin hallituksen esitykset, valtioneuvosto, oikeusministeriö, LVM, TEM, VM |
| Valvontaviranomaiset | tietosuojavaltuutettu, Traficom, EDPB, EDPS, Puolan UODO |
| Oikeudelliset julkaisut | Helda, Lauda, UTUPub, UEF eRepo, JYX, Doria, Osuva |
| Muut uutiset ja blogit | Edilex, IAPP, Asianajajaliitto |
| Kyberturvallisuus | Kyberturvallisuuskeskus, ENISA (uutiset ja julkaisut), sisäministeriö |

Asianajotoimistojen omat julkaisut (Roschier, Hannes Snellman, Castrén &
Snellman, Krogerus) on poistettu lähteistä tietoisesti, sivu keskittyy
viranomaisten ja tuomioistuinten omaan aineistoon.

Kolme uutiskirjeen lähdettä jää käsityöksi. Eduskunnan VaskiData palauttaa
`XmlData`-möykkyjä ilman käyttökelpoista päivämääräsaraketta. Bird & Birdin
omat julkaisut piirtyvät kokonaan selaimessa, eli `twobirds.com/en/insights`
vastaa 60 kilotavulla JavaScriptiä ja nollalla artikkelilla, eikä yhtään
RSS-polkua ole. Tampereen Trepo vastaa OAI-polkuun 200 mutta nollalla
tietueella. Nämä näkyvät sivun lähdepaneelissa, jotta sivu kertoo itse mitä
se ei kata.

## Käyttöönotto

1. Luo GitHubiin uusi repo, esimerkiksi `oikeusfeed`, ja työnnä nämä tiedostot sinne.
2. Tarkista `.github/workflows/update.yml`. Rivin `--base-url` osoite pitää olla
   `https://KAYTTAJATUNNUS.github.io/REPON-NIMI/`.
3. Mene repon **Settings → Pages**. Valitse Source: *Deploy from a branch*,
   Branch: `main` ja kansio `/docs`. Tallenna.
   Pages toimii ilmaistilillä vain julkisessa repossa.
4. Mene **Actions**-välilehdelle, valitse työnkulku ja paina *Run workflow*.
   Ensimmäinen ajo kestää noin 2 minuuttia, koska EU-kysely on hidas.
5. Sivu löytyy osoitteesta `https://lslander.github.io/Tietosuojaseuranta/`.
   Huomaa isot ja pienet kirjaimet. Käyttäjätunnus on aina pienellä, mutta
   repon nimi säilyttää kirjainkoon polussa.

Lisää osoite puhelimen aloitusnäytölle tai tilaa `feed.xml` RSS-lukijaan.

## Paikallinen ajo

```bash
pip install -r requirements.txt

python main.py --dry-run          # näyttää osumat, ei kirjoita tiedostoja
python main.py                    # kirjoittaa docs-kansion
python main.py --only kko,kho     # vain valitut lähteet
python main.py -v                 # enemmän lokia
```

`--dry-run` on nopein tapa säätää avainsanoja. Muuta `sources.yaml`, aja
uudelleen ja katso mitä tulee läpi.

## Suodatuksen säätäminen

`sources.yaml` sisältää kolme avainsanalistaa:

- `must_any` on portti. Vähintään yhden termin pitää osua otsikkoon,
  asiasanoihin tai tiivistelmään. Jos lista on tyhjä, kaikki pääsee läpi.
- `boost` nostaa jutun tärkeäksi. Nämä näkyvät sivulla korostettuna.
- `never` pudottaa jutun pois, vaikka `must_any` osuisi. Tähän kuuluvat
  esimerkiksi webinaarikutsut ja vuosikertomukset. Huomaa että `never`
  katsotaan vain otsikosta ja asiasanoista, ei tiivistelmästä. Muuten
  Kyberturvallisuuskeskuksen viikkokatsaus putoaa pois aina kun siinä
  mainitaan ohimennen jokin webinaari.

Näiden lisäksi on kolme lähdekohtaista asetusta, jotka toimivat eri tasolla:

- `always_include: true` päästää lähteen jutut läpi ilman `must_any`-osumaa.
  Tämä on tietosuojavaltuutetulla ja EDPB:llä, koska ne käsittelevät jo
  valmiiksi vain tietosuojaa. `never`-lista pätee silti.
- `require_any` on lähteen oma lisäportti, joka ajetaan ennen globaalia
  suodatusta. Julkaisuarkistoissa se vaatii oikeustieteellisen termin.
  Ilman sitä feediin päätyi konenäköä käsitteleviä diplomitöitä, koska termi
  "tekoäly" osui `must_any`-listaan.
- `never_any` on lähteen oma poissulku, joka katsotaan otsikosta ja
  asiasanoista. Kyberturvallisuuskeskuksella se pudottaa yksittäiset
  tuotehaavoittuvuustiedotteet ("Kriittinen haavoittuvuus X -tuotteissa"),
  joita tulee niin tiheään että ne peittivät alleen oikeudelliset jutut.
  Globaali `never` ei kelpaa tähän, koska sama sana on komission
  kyberkestävyyssäädöstä koskevassa tiedotteessa juuri se mitä haetaan.

## Aiheluokat

`sources.yaml` sisältää `topics`-lohkon, joka on aiheluokan nimi ja lista
termejä. Juttu saa kaikki ne luokat, joiden termeistä vähintään yksi osuu.
Sama juttu voi kuulua useaan luokkaan, koska tietosuojavaltuutetun ratkaisu
kasvojentunnistuksesta on sekä tietosuojaa että tekoälyä.

Luokat näkyvät sivulla omana nappirivinään lähdenappien yläpuolella ja
RSS-syötteessä `<category>`-elementteinä. Sivulla lähde- ja aihesuodatus
yhdistyvät JA-ehdolla, mutta saman ryhmän sisällä TAI-ehdolla. Jos juttu ei
osu yhteenkään luokkaan, se näkyy vain silloin kun aihesuodatus on pois
päältä. Tämä kannattaa pitää mielessä, jos joku katoaa näkyvistä.

Vertailu on yksinkertainen osajonohaku pienillä kirjaimilla. Siksi listassa
on katkaistuja sanoja kuten `henkilötiet`, joka osuu muotoihin
"henkilötieto", "henkilötietojen" ja "henkilötietoja". Suomen taivutus
hoituu tällä ilman regexiä.

Jos osumia tulee liian vähän, kasvata `window_days`-arvoa tai lisää termejä.
Jos roskaa tulee liikaa, siirrä termi `must_any`-listasta pois tai lisää
tarkempi ilmaus `never`-listaan.

## Ulkoasu

Värit ja fontit ovat `render.py`-tiedoston `:root`-lohkossa. Ilme noudattaa
Bird & Birdin mallipohjaa: petroli `#005C82`, korostusväri `#FFA169` ja vaalea
mintunvihreä tausta. Otsikot ovat Georgialla ja leipäteksti groteskilla, mikä
on sama pari kuin toimiston Office-pohjissa. Georgia on valmiina jokaisessa
käyttöjärjestelmässä, joten sivu ei lataa fontteja ulkopuolelta ja pysyy
yhtenä tiedostona. Tumma tila noudattaa samaa palettia. Ulkoisen fontin
välttämisessä on myös oikeudellinen puoli: Google Fonts -lataus välittää
kävijän IP-osoitteen Googlelle, mistä München I -maakäräjäoikeus tuomitsi
sivuston ylläpitäjän korvauksiin (LG München I 20.1.2022, 3 O 17493/20).

Kaikki tekstin ja taustan väriparit ylittävät WCAG 2.1 AA -rajan 4,5:1, ja
useimmat myös AAA-rajan 7:1. Fokusreuna on kolmen pikselin petroli
`:focus-visible`-tilassa, koska suodattimia selataan sarkaimella.

## Sivun rakenne

Yläosa kertoo mitä sivu on, mistä aineisto tulee ja mikä aikaikkuna on
käytössä. Sen alla on avattava lähdepaneeli, joka näyttää jokaisen lähteen
kohdalla, montako juttua siitä saatiin ennen suodatusta ja vastasiko se
lainkaan. Ero on tärkeä: nolla tarkoittaa että lähde vastasi eikä sillä ollut
mitään, kun taas "ei saatu" tarkoittaa että aineisto puuttuu sivulta
kokonaan. Paneeli listaa lopuksi ne uutiskirjeen lähteet, jotka jäävät
käsityöksi.

Tilatieto kulkee `fetchers.py`-tiedoston `SourceResult`-luokassa
`main.py`-tiedoston kautta `render.py`-tiedostoon. Jos lisäät lähdetyypin,
palauta `SourceResult`, älä pelkkää listaa.

Sama tieto on `data.json`-tiedostossa avaimen `sources` alla. Huomaa että
`data.json` ei ole enää pelkkä lista vaan olio, jolla on kentät `generated`,
`window_days`, `sources` ja `items`.

## Lähteiden lisääminen

Lähde on yksi merkintä `sources.yaml`-tiedostossa. Koodia ei tarvitse muuttaa,
jos lähdetyyppi on jo olemassa:

```yaml
- id: oma-lahde
  name: "Lähteen nimi sivun alaviitteeseen"
  type: plain_rss          # wp_rss, plain_rss, eu_sparql, html_list, oai_pmh, finlex
  court: "TUNNUS"          # lyhenne suodatusnappiin
  weight: 2                # 1-3, vaikuttaa järjestykseen
  optional: true           # virhe ei kaada ajoa
  browser: true            # selaimen tunniste, jos palvelin torjuu robotin
  url: "https://..."
  require_any: []          # valinnainen lisäportti
  never_any: []            # valinnainen poissulku
```

Tyypit:

- `wp_rss` on tuomioistuinlaitoksen WordPress-syöte. Nämä antavat asiasanat
  `<category>`-elementteinä, mikä on suodatuksen kannalta tärkein tieto,
  koska otsikko on pelkkä tunnus kuten "KKO:2026:62".
- `plain_rss` on mikä tahansa tavallinen RSS tai Atom.
- `eu_sparql` kysyy unionin tuomioistuimen ratkaisut EU:n Cellar-tietokannasta.
- `html_list` raapii linkit HTML-sivulta. `link_pattern` rajaa mitkä linkit
  kelpaavat.
- `oai_pmh` hakee yliopistojen julkaisuarkistot. Asetukset ovat
  `lookback_days` (kuinka kaukaa taaksepäin haetaan), `max_pages` (yksi sivu
  on 100 tietuetta) ja `type_contains` (millaiset julkaisutyypit kelpaavat).
- `finlex` lukee säädöskokoelman ja hallituksen esitykset listasivun
  HTML:stä. Vaatii `browser: true`.

`html_list` on näistä säädettävin, koska listasivut ovat erilaisia:

- `link_pattern` rajaa mitkä linkit kelpaavat, `skip_pattern` pudottaa
  osastosivut silloin kun ne ovat saman polun alla kuin artikkelit.
- `min_title_len` pudottaa navigaatiolinkit, oletus on 20 merkkiä.
- `strip_title_prefix` siivoaa otsikon edestä turhan osan. Edilex kirjoittaa
  kellonajan otsikkoon muodossa "18.9.2026 16.00 Otsikko".
- `detail_date: true` hakee puuttuvan päivämäärän jutun omalta sivulta.
  Tämä maksaa yhden pyynnön juttua kohden, joten se on päällä vain
  IAPP:lla, jonka listasivulla ei ole päivämäärää missään muodossa.

Palvelimen hiljainen torjunta kannattaa pitää mielessä. `europa.eu` vastaa
rehelliselle tunnisteelle koodilla 202 ja tyhjällä rungolla, eikä
`raise_for_status` nosta siitä virhettä. Lähde näyttäisi silloin vihreältä ja
tyhjältä, vaikka se on estetty. Siksi `_get` pitää alle 200 tavun vastausta
aina virheenä ja `browser: true` antaa lähteelle selaimen tunnisteen.

Valtioneuvoston hallinnonalan sivut pyörivät Liferaylla, joka tarjoaa RSS:n
osoitteessa `/<sivu>/-/asset_publisher/<TUNNUS>/rss`. Tunnusta ei näy
käyttöliittymässä, joten se pitää kaivaa sivun HTML-lähteestä. Tietosuoja.fi
ja tem.fi toimivat näin. Valtioneuvosto.fi ja lvm.fi eivät tarjoa syötettä
lainkaan, joten ne raavitaan `html_list`-tyypillä.

DSpace-arkistoissa on yksi ansa. Versio 7 siirsi OAI-rajapinnan polkuun
`/server/oai/request`, kun vanhemmat asennukset käyttävät polkua
`/oai/request`. Helda, UTUPub ja UEF ovat uudella polulla, Lauda ja Doria
vanhalla. Väärä polku palauttaa 404 tai nolla tietuetta ilman virheilmoitusta.

Uusi lähdetyyppi vaatii funktion `fetchers.py`-tiedostoon ja merkinnän
`FETCHERS`-sanakirjaan.

## Finlex ilman rajapintaa

Finlexillä ei ole avointa rajapintaa. `api.finlex.fi` vastaa 401,
`opendata.finlex.fi` vastaa 403 ja Akoma Ntoso -polut oikeustapauksiin
palauttavat 404. Oikeuskäytäntö haetaan siksi tuomioistuinten omilta
sivuilta, joilla WordPress tarjoaa syötteen ilman avainta.

Säädöskokoelma ja hallituksen esitykset luetaan listasivun HTML:stä omalla
`finlex`-tyypillä. Sivusto on Next.js, joten valmista DOM-listaa ei ole vaan
aineisto tulee palvelinkomponenttien virtana, jossa JSON on pakattu kahteen
kertaan. Otsikot löytyvät linkkien `aria-label`-arvoista muodossa
"853/2026, Valtioneuvoston asetus ...". Listasivulla ei ole päivämääriä ja
säädöksiä on vuodessa yli 800, joten hakija suodattaa ensin otsikosta
`require_any`-listalla ja hakee julkaisupäivän vasta jäljelle jääneiden
säädösten omilta sivuilta. Näin verkkopyyntöjä tulee kymmeniä eikä satoja.

Tietosuojavaltuutetun ratkaisut julkaistaan Finlexissä, joten niitä seurataan
toimiston ajankohtaissivulta. Sieltä löytyvät seuraamusmaksut ja
merkittävimmät ratkaisut uutisina.

## Tunnetut rajoitukset

- Käräjäoikeuksilla ei ole omaa ratkaisulistaa, koska vanhat `oikeus.fi`-
  osoitteet vastaavat 404. Ne katetaan tuomioistuinlaitoksen yhteisellä
  ajankohtaissyötteellä, joka kertoo samat asiat tiedotteina, ei
  ratkaisuselosteina. `court_patterns`-asetus lukee otsikosta minkä
  oikeusasteen juttu on kyseessä (myös taivutusmuodoissa, ja KHO erotellaan
  tavallisesta hallinto-oikeudesta) ja näyttää sen sivun oikeusaste-
  suodattimessa omana nappinaan yleisnimen "Tuomioistuimet" sijaan.
  Hallinto-oikeuksilla ja hovioikeuksilla sen sijaan on oma lähteensä
  (`hao-ratkaisut`, `hovi-ratkaisut`), joka lukee suoraan tuomioistuimet.fi:n
  omat ratkaisulistat. Näillä on oikeat ratkaisuselosteet ja tuomioistuimen
  itsensä antama asiasanaluettelo (esim. "Tietosuoja – Asiakirjajulkisuus"),
  joka on huomattavasti tarkempi kuin ajankohtaissyötteen otsikko ja tekee
  avainsanasuodatuksesta osuvampaa. Sivu näyttää satoja ratkaisuja
  kaikista aihepiireistä, joten näillä lähteillä ei ole omaa
  `require_any`-listaa, vaan ne luottavat yleiseen `must_any`-suodatukseen.
- Unionin tuomioistuimen SPARQL-haku hakee kaikki tuomiot aihealueesta
  riippumatta, joten pelkkä yleinen avainsana ("seuraamusmaksu") saattoi
  päästää läpi tietosuojaan liittymättömiä ratkaisuja (esim. liikennealan
  sakkoasia). `eu-courts`-lähteellä on nyt oma, tarkempi `require_any`-lista,
  joka karsii nämä pois ennen yleistä avainsanasuodatusta.
- EDPS:n oma uutissivu on JavaScript-haasteen takana ja vastaa 202 myös
  selaimen tunnisteella, joten nostot luetaan etusivulta. Saalis on pieni.
- Doria ja muut yliopistojen OAI-PMH-arkistot katkaisevat yhteyden joskus
  kesken vastauksen. Haku yrittää nyt saman pyynnön uudelleen kolme kertaa
  kasvavalla odotuksella ennen kuin lähde merkitään epäonnistuneeksi, joten
  yksittäinen katkos ei enää yleensä näy lähdepaneelissa punaisena.
- UODO:n etusivun asettelu vaihtelee, ja joskus sinne ilmestyy pysyviä
  ohjesivuja ("What rights does the GDPR give you?") uutisten sekaan
  `link_pattern`-suodatuksesta huolimatta. Näiden otsikon perässä on aina
  sivun oma "Check"-nappi, joten `never_any: ["check"]` pudottaa ne pois
  toisena suojakerroksena.
- Unionin tuomioistuimen suomenkielinen toisinto ilmestyy viiveellä.
  Skripti ottaa englanninkielisen asiasanoituksen varalle ja korvaa sen
  suomenkielisellä, kun se on saatavilla.
- HTML-listauksesta päivämäärä ei aina löydy. Hakija etsii sen ensin linkin
  läheltä, sitten osoitteesta ja lopuksi jutun omalta sivulta, jos lähteessä
  on `detail_date: true`. Jos mikään ei tuota tulosta, juttu saa merkinnän
  "pvm arvioitu" ja päiväksi tulee ajopäivä. Arvatut jäävät järjestyksessä
  saman päivän varmojen juttujen jälkeen, jotta ne eivät nouse kärkeen.
- Julkaisuarkistot ovat hitaita ja epätasaisia. Yhdestä yliopistosta voi tulla
  kymmeniä osumia ja toisesta yksi, koska tietueiden asiasanoitus vaihtelee.
  Tampereen Trepo jätettiin pois, koska yhteys aikakatkeaa toistuvasti.
- `oai_pmh` tarvitsee `lxml`-kirjaston, koska BeautifulSoupin XML-jäsennin ei
  toimi ilman sitä. Se on `requirements.txt`-tiedostossa.
- Seuranta on apuväline. Tarkista ratkaisu aina alkuperäisestä lähteestä
  ennen kuin nojaat siihen.
