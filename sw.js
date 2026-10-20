// Service worker da app de picking: deixa a app abrir sem rede.
//
// - A página vai SEMPRE primeiro à rede, para os tablets nunca ficarem presos
//   numa versão antiga. Só se a rede falhar (ou demorar mais de 6 s) é que se
//   usa a última cópia guardada -- e mesmo aí a resposta da rede, se chegar
//   tarde, fica guardada para a próxima vez.
// - Imagens, manifesto e as bibliotecas do cdnjs servem-se da cópia e
//   atualizam-se em segundo plano.
// - Os dados (Supabase) não passam por aqui: a app guarda a sua própria cópia,
//   com a hora, para poder dizer ao operador de quando são.
//
// Mudar VERSAO só é preciso quando a lógica deste ficheiro muda; as versões
// novas da app chegam sozinhas pela regra da página.
const VERSAO = 'picking-v1';
const PAGINA = new URL('__pagina__', self.registration.scope).href;
const TEMPO_PAGINA_MS = 6000;
const ESTATICOS = ['logo.png', 'header-bg.png', 'manifest.webmanifest'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(VERSAO)
      .then(c => c.addAll(ESTATICOS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(chaves => Promise.all(chaves.filter(k => k.startsWith('picking-') && k !== VERSAO).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Pede à rede e guarda a resposta com a chave dada. A gravação fica presa ao
// evento logo aqui (waitUntil tem de ser chamado durante o evento): assim uma
// resposta que chegue depois de já se ter servido a cópia continua a ser guardada.
function pedirEGuardar(e, chave) {
  let guardar = Promise.resolve();
  const daRede = fetch(e.request).then(resp => {
    // As bibliotecas do cdnjs vêm "opacas" (pedido sem CORS): guardam-se na mesma
    if (resp.ok || resp.type === 'opaque') {
      const copia = resp.clone();
      guardar = caches.open(VERSAO).then(c => c.put(chave, copia));
    }
    return resp;
  });
  e.waitUntil(daRede.then(() => guardar, () => {}));
  return daRede;
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname.endsWith('supabase.co')) return;

  if (req.mode === 'navigate') {
    e.respondWith(paginaRedePrimeiro(pedirEGuardar(e, PAGINA)));
  } else if (url.origin === self.location.origin || url.hostname === 'cdnjs.cloudflare.com') {
    e.respondWith(copiaEAtualiza(req, pedirEGuardar(e, req)));
  }
});

async function paginaRedePrimeiro(daRede) {
  try {
    return await Promise.race([
      daRede,
      new Promise((_, rej) => setTimeout(() => rej(new Error('rede lenta')), TEMPO_PAGINA_MS))
    ]);
  } catch (err) {
    const guardada = await caches.match(PAGINA);
    if (guardada) return guardada;
    return daRede;   // nunca houve cópia: a rede é a única hipótese
  }
}

async function copiaEAtualiza(req, daRede) {
  const guardada = await caches.match(req);
  if (guardada) {
    daRede.catch(() => {});   // sem rede fica a cópia; a falha não interessa
    return guardada;
  }
  return daRede;
}
