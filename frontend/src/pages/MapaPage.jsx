import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useCondominios, ehCondominioBancada } from '../components/CondominioSelect.jsx'
import { supabase } from '../supabaseClient.js'

/**
 * Mapa dos pontos de recarga.
 *
 * Mostra os locais de verdade (latitude/longitude vêm do /condominios, db/20).
 * O estande do Next (perfil 'bancada') não entra: é um ponto de demonstração,
 * não um lugar para onde alguém vai dirigir.
 *
 * Mapa: Leaflet + azulejos da CARTO (dados do OpenStreetMap). Sem chave e sem
 * cartão de crédito. O app manda `no-referrer` (index.html), e há provedor de
 * azulejo que recusa pedido sem Referer - o resultado era o fundo cinza
 * quadriculado, só com zoom e pinos. Por isso:
 *   - os azulejos (e só eles) saem com `strict-origin-when-cross-origin`:
 *     o provedor vê a ORIGEM (http://host:porta), nunca a página;
 *   - se a base não carregar (rede da faculdade, bloqueio de rastreamento do
 *     navegador, provedor fora), o mapa troca sozinho para a próxima da lista.
 * A rota abre no Google Maps pelo ENDEREÇO escrito, não pela coordenada: no
 * Brasil o OSM quase não tem número de casa, então a coordenada pode ser o
 * meio da rua; o Google resolve o número e leva até a porta.
 * "Usar minha localização" pede permissão ao navegador e só funciona em
 * https ou em localhost (regra do navegador, não nossa).
 */

const CENTRO_SP = [-23.53, -46.75]

const ATRIB_OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const ATRIB_CARTO = `${ATRIB_OSM} &copy; <a href="https://carto.com/attributions">CARTO</a>`
const ATRIB_ESRI = 'Azulejos &copy; <a href="https://www.esri.com">Esri</a>'

/** Bases em ordem de preferência; a seguinte só entra se a anterior falhar. */
function basesDoMapa(escuro) {
  return [
    { url: `https://{s}.basemaps.cartocdn.com/${escuro ? 'dark_all' : 'rastertiles/voyager'}/{z}/{x}/{y}{r}.png`,
      subdomains: 'abcd', maxZoom: 20, attribution: ATRIB_CARTO },
    { url: `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${escuro ? 'World_Dark_Gray_Base' : 'World_Light_Gray_Base'}/MapServer/tile/{z}/{y}/{x}`,
      maxZoom: 16, attribution: ATRIB_ESRI },
    { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      maxZoom: 19, attribution: ATRIB_OSM, className: escuro ? 'tiles-noite' : '' },
  ]
}
const FALHAS_PARA_TROCAR = 6        // azulejos com erro antes do primeiro que carrega
const ESPERA_TROCA_MS = 8000        // nenhum azulejo em 8 s: a base não responde

function distanciaKm(a, b) {
  const rad = (g) => (g * Math.PI) / 180
  const dLat = rad(b[0] - a[0])
  const dLon = rad(b[1] - a[1])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(h))
}

function fmtKm(km) {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} km`
}

function linkRota(local) {
  const destino = local.endereco || `${local.latitude},${local.longitude}`
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destino)}`
}

function pino(ativo, livres) {
  return L.divIcon({
    className: '',
    html: `<span class="pino-mapa${ativo ? ' pino-ativo' : ''}${livres ? '' : ' pino-sem-vaga'}"><span>${livres}</span></span>`,
    iconSize: [34, 42],
    iconAnchor: [17, 40],
  })
}

function MapaPage({ condominioAtual, onVerLocal }) {
  const { condominios, carregando, erro } = useCondominios()
  const [livres, setLivres] = useState({})          // condominio_id -> { livres, total }
  const [eu, setEu] = useState(null)                // [lat, lng] de quem usa
  const [avisoLocal, setAvisoLocal] = useState('')
  const [escolhido, setEscolhido] = useState(null)
  const caixa = useRef(null)
  const mapa = useRef(null)
  const camadaPinos = useRef(null)
  const pinoEu = useRef(null)

  const locais = useMemo(
    () => condominios.filter((c) => !ehCondominioBancada(c) && c.latitude != null && c.longitude != null),
    [condominios],
  )
  const semCoordenada = !carregando && condominios.length > 0 && locais.length === 0

  const ordenados = useMemo(() => {
    const lista = locais.map((l) => ({ ...l, km: eu ? distanciaKm(eu, [l.latitude, l.longitude]) : null }))
    return eu ? lista.sort((a, b) => a.km - b.km) : lista
  }, [locais, eu])

  // Disponibilidade por local: lida direto do banco (RLS libera leitura de carregadores).
  useEffect(() => {
    if (!locais.length) return
    let vivo = true
    supabase.from('carregadores').select('condominio_id, status')
      .in('condominio_id', locais.map((l) => l.id))
      .then(({ data }) => {
        if (!vivo || !data) return
        const porLocal = {}
        for (const c of data) {
          const p = (porLocal[c.condominio_id] ||= { livres: 0, total: 0 })
          p.total += 1
          if (c.status === 'disponivel') p.livres += 1
        }
        setLivres(porLocal)
      })
    return () => { vivo = false }
  }, [locais])

  // Cria o mapa uma vez. A base segue o tema do app (claro/escuro).
  useEffect(() => {
    if (!caixa.current || mapa.current) return
    const escuro = document.documentElement.dataset.tema !== 'claro'
    const m = L.map(caixa.current, { zoomControl: true, attributionControl: true }).setView(CENTRO_SP, 11)
    const bases = basesDoMapa(escuro)
    let camada = null
    let relogio = null

    function usarBase(i) {
      clearTimeout(relogio)
      camada?.remove()
      const { url, ...opcoes } = bases[i]
      let falhas = 0
      let carregou = false
      const esta = L.tileLayer(url, { ...opcoes, referrerPolicy: 'strict-origin-when-cross-origin' })
      // Evento de uma base já descartada (azulejo cancelado na troca) não conta.
      const proxima = () => { if (camada === esta && !carregou && i + 1 < bases.length) usarBase(i + 1) }
      camada = esta
        .on('tileload', () => { carregou = true; if (camada === esta) clearTimeout(relogio) })
        .on('tileerror', () => { if (++falhas >= FALHAS_PARA_TROCAR) proxima() })
        .addTo(m)
      relogio = setTimeout(proxima, ESPERA_TROCA_MS)
    }

    usarBase(0)
    camadaPinos.current = L.layerGroup().addTo(m)
    mapa.current = m
    return () => { clearTimeout(relogio); m.remove(); mapa.current = null }
  }, [])

  // Pinos: refeitos quando muda a lista, a disponibilidade ou o local escolhido.
  useEffect(() => {
    const m = mapa.current
    if (!m || !camadaPinos.current) return
    camadaPinos.current.clearLayers()
    for (const l of locais) {
      const d = livres[l.id]
      L.marker([l.latitude, l.longitude], {
        icon: pino(l.id === (escolhido || condominioAtual), d?.livres ?? '·'),
        title: l.nome,
        keyboard: true,
      }).on('click', () => setEscolhido(l.id)).addTo(camadaPinos.current)
    }
    if (locais.length && !eu && !escolhido) {
      m.fitBounds(L.latLngBounds(locais.map((l) => [l.latitude, l.longitude])), { padding: [48, 48], maxZoom: 13 })
    }
  }, [locais, livres, escolhido, condominioAtual, eu])

  function localizar() {
    setAvisoLocal('')
    if (!navigator.geolocation) {
      setAvisoLocal('Este navegador não informa a localização.')
      return
    }
    if (!window.isSecureContext) {
      setAvisoLocal('A localização só funciona em https (ou localhost). No endereço publicado ela funciona.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const pos = [p.coords.latitude, p.coords.longitude]
        setEu(pos)
        const m = mapa.current
        if (!m) return
        pinoEu.current?.remove()
        pinoEu.current = L.circleMarker(pos, { radius: 8, color: '#fff', weight: 3, fillColor: '#2f80ff', fillOpacity: 1 })
          .bindTooltip('Você está aqui').addTo(m)
        const alvos = [pos, ...locais.map((l) => [l.latitude, l.longitude])]
        m.fitBounds(L.latLngBounds(alvos), { padding: [48, 48], maxZoom: 14 })
      },
      (e) => setAvisoLocal(e.code === 1 ? 'Permissão de localização negada.' : 'Não foi possível obter sua localização.'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  function focar(l) {
    setEscolhido(l.id)
    mapa.current?.flyTo([l.latitude, l.longitude], 15, { duration: 0.8 })
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Mapa de pontos</h2>
          <p className="mt-1 text-sm text-mute">Onde carregar, quantos pontos estão livres agora e como chegar.</p>
        </div>
        <button type="button" onClick={localizar}
                className="flex items-center gap-2 rounded-chip border border-line bg-panel px-4 py-2 text-sm text-ink transition-colors hover:border-flux/50">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="12" cy="12" r="3.5" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
          </svg>
          Usar minha localização
        </button>
      </div>

      {avisoLocal && <p className="mb-3 text-sm text-queue">{avisoLocal}</p>}
      {erro && <p className="mb-3 text-sm text-flux">{erro}</p>}
      {semCoordenada && (
        <p className="mb-3 rounded-chip border border-queue/40 bg-queue/10 px-4 py-2.5 text-sm text-queue">
          Os locais ainda não têm coordenada no banco (migration db/20).
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative min-w-0 rounded-panel">
          <div ref={caixa} className="realce mapa-hud relative z-0 h-[52vh] min-h-[320px] overflow-hidden rounded-panel border border-line lg:h-[620px]"
               role="region" aria-label="Mapa dos pontos de recarga" />
          <span className="condutor" style={{ '--cond-dur': '9s' }} aria-hidden="true" />
        </div>

        <ul className="space-y-2">
          {ordenados.map((l) => {
            const d = livres[l.id]
            const ativo = l.id === (escolhido || condominioAtual)
            return (
              <li key={l.id}>
                <div className={`rounded-panel border bg-panel p-4 transition-colors ${ativo ? 'border-flux/60' : 'border-line'}`}>
                  <button type="button" onClick={() => focar(l)} className="w-full text-left">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="font-medium text-ink">{l.nome}</p>
                      {l.km != null && <span className="num shrink-0 text-xs text-mute">{fmtKm(l.km)}</span>}
                    </div>
                    <p className="mt-0.5 text-xs leading-snug text-dim">{l.endereco}</p>
                    <p className={`mt-2 text-sm ${d?.livres ? 'text-live' : 'text-mute'}`}>
                      {d ? `${d.livres} de ${d.total} pontos livres` : 'Consultando pontos…'}
                    </p>
                  </button>
                  <div className="mt-3 flex gap-2">
                    <button type="button" onClick={() => onVerLocal(l.id)}
                            className="flex-1 rounded-chip bg-flux px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-flare">
                      Ver carregadores
                    </button>
                    <a href={linkRota(l)} target="_blank" rel="noopener noreferrer"
                       className="flex-1 rounded-chip border border-line px-3 py-2 text-center text-sm text-ink transition-colors hover:border-flux/50">
                      Como chegar
                    </a>
                  </div>
                </div>
              </li>
            )
          })}
          {carregando && <li className="skeleton h-28 rounded-panel" />}
        </ul>
      </div>
    </div>
  )
}

export default MapaPage
