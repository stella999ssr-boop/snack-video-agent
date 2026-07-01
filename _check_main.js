const API = '/api/v1';

// ═══ 路由 ═══
let currentPage = 'generate';
const pages = ['generate','archive','feedback'];

function navigate(hash) {
  const page = (hash || window.location.hash || '#generate').replace('#','');
  if (!pages.includes(page)) return navigate('#generate');
  currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  document.querySelectorAll('.nav-link').forEach(l => {
    l.classList.toggle('bg-indigo-50', l.dataset.page === page);
    l.classList.toggle('text-primary', l.dataset.page === page);
  });
  if (page === 'archive') loadArchive();
  if (page === 'feedback') initFeedback();
}

window.addEventListener('hashchange', () => navigate());
navigate();

// ═══ Toast ═══
function toast(msg, type='info') {
  const el = document.getElementById('toast');
  const colors = { info:'bg-gray-800', success:'bg-green-600', error:'bg-red-500' };
  el.className = 'fixed top-4 right-4 z-[9999] px-4 py-2 rounded-lg text-white text-sm shadow-lg fade-in ' + (colors[type]||colors.info);
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(el._t);
  el._t = setTimeout(() => el.style.display = 'none', 3000);
}

// ═══ 星级 ═══
function starHTML(n) {
  let h = '';
  for (let i=1;i<=5;i++) h += `<i class="fa fa-star${i<=n?' star':'-o'} text-xs"></i>`;
  return h;
}

// ═══ 标签输入组件 ═══
document.querySelectorAll('.tag-input').forEach(wrapper => {
  const input = wrapper.querySelector('.tag-inner-input');
  const field = wrapper.dataset.field;
  wrapper.addEventListener('click', () => input.focus());
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addTag(wrapper, input.value.trim(), field); input.value = ''; }
    if (e.key === 'Backspace' && !input.value && wrapper.querySelectorAll('.tag').length) {
      const last = wrapper.querySelector('.tag:last-of-type');
      if (last) { last.remove(); updateTagField(wrapper, field); }
    }
  });
});
function addTag(wrapper, text, field) {
  if (!text) return;
  const tag = document.createElement('span');
  tag.className = 'tag bg-indigo-50 text-primary text-xs';
  tag.innerHTML = `${text}<i class="fa fa-times cursor-pointer hover:text-red-400" onclick="this.parentElement.remove();updateTagField(this.closest('.tag-input'),'${field}')"></i>`;
  wrapper.insertBefore(tag, wrapper.querySelector('.tag-inner-input'));
  updateTagField(wrapper, field);
}
function updateTagField(wrapper, field) {
  const tags = [...wrapper.querySelectorAll('.tag')].map(t => t.textContent.trim());
  let hidden = wrapper.querySelector('input[type="hidden"]');
  if (!hidden) { hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = field; wrapper.appendChild(hidden); }
  hidden.value = JSON.stringify(tags);
}

// ═══ 文件上传 ═══
const extraImages = [];

async function uploadFile(file, type) {
  const formData = new FormData();
  formData.append('file', file);
  const resp = await fetch(`${API}/upload/${type}`, { method: 'POST', body: formData });
  if (!resp.ok) throw new Error('上传失败');
  const data = await resp.json();
  return data.url;
}

async function handleFilePick(input, previewId, hiddenId) {
  const file = input.files[0];
  if (!file) return;
  try {
    const type = file.type.startsWith('video/') ? 'video' : 'image';
    const url = await uploadFile(file, type);
    document.getElementById(hiddenId).value = url;

    const preview = document.getElementById(previewId);
    // 从 previewId 提取前缀如 "main-image" 或 "video"
    const prefix = previewId.replace('-preview', '');
    const icon = document.getElementById(prefix + '-icon');
    const text = document.getElementById(prefix + '-text');

    if (preview) {
      if (type === 'video') {
        preview.src = url;
      } else {
        preview.src = url;
      }
      preview.classList.remove('hidden');
    }
    if (icon) icon.classList.add('hidden');
    if (text) text.textContent = file.name;
    toast('上传成功', 'success');
  } catch (err) {
    toast('上传失败: ' + err.message, 'error');
    input.value = '';
  }
}

async function handleExtraImage(input) {
  const file = input.files[0];
  if (!file) return;
  try {
    const url = await uploadFile(file, 'image');
    extraImages.push(url);

    const container = document.getElementById('extra-images-container');
    const thumb = document.createElement('div');
    thumb.className = 'relative w-20 h-20 rounded-lg overflow-hidden border';
    thumb.innerHTML = `<img src="${url}" class="w-full h-full object-cover">
      <button class="absolute top-0 right-0 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs" onclick="event.stopPropagation();removeExtraImage(this, '${url}')">&times;</button>`;
    container.insertBefore(thumb, document.getElementById('add-image-btn'));
    input.value = '';
    toast('图片已上传', 'success');
  } catch (err) {
    toast('上传失败: ' + err.message, 'error');
    input.value = '';
  }
}

function removeExtraImage(btn, url) {
  btn.parentElement.remove();
  const idx = extraImages.indexOf(url);
  if (idx >= 0) extraImages.splice(idx, 1);
}

// ═══ 进度条 ═══
function updateProgress(stage) {
  const stages = ['analyze','searching','generating','rendering','quality_checking','done'];
  const idx = stages.indexOf(stage);
  document.querySelectorAll('.stage-dot').forEach((d,i) => {
    d.classList.remove('active','done');
    if (i < idx) d.classList.add('done');
    if (i === idx) d.classList.add('active');
  });
}
const stageMap = { searching:0, generating:1, rendering:2, quality_checking:3, compliance_checking:4, done:5 };

// ═══ 页面 1：素材生成 ═══
let pollingTimer = null;

document.getElementById('generate-form').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('submit-btn');

  // 前端校验必填字段
  const productName = e.target.querySelector('[name="product_name"]').value.trim();
  const categoryL2 = e.target.querySelector('[name="category_l2"]').value.trim();
  if (!productName) { toast('请填写商品名称', 'error'); return; }
  if (!categoryL2) { toast('请填写二级类目', 'error'); return; }

  btn.disabled = true;
  btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> 正在生成...';

  const fd = new FormData(e.target);
  const gatherTags = (name) => {
    const el = document.querySelector(`.tag-input[data-field="${name}"] input[type="hidden"]`);
    if (el) { try { return JSON.parse(el.value); } catch(_){} }
    return [];
  };

  const mainImage = document.getElementById('main-image-url').value || null;
  const productVideo = document.getElementById('video-url').value || null;

  const body = {
    product_name: fd.get('product_name'),
    category_l1: fd.get('category_l1') || '零食',
    category_l2: fd.get('category_l2'),
    shop_product_id: fd.get('product_name') + '_' + Date.now(),
    price: {
      unit_price: parseFloat(fd.get('unit_price')) || 9.9,
      original_price: parseFloat(fd.get('original_price')) || 0,
      discount_rate: fd.get('discount_rate') || '',
    },
    features: {
      selling_points: gatherTags('selling_points'),
      taste_tags: gatherTags('taste_tags'),
      use_scene: gatherTags('use_scene'),
      stock_status: fd.get('stock_status') || '',
    },
    assets: {
      product_main_image: mainImage,
      product_images: extraImages.length > 0 ? extraImages : null,
      product_video: productVideo,
    },
  };

  try {
    const resp = await fetch(`${API}/creative/generate`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '请求失败');
    document.getElementById('generate-form-card').classList.add('hidden');
    toast('素材生成任务已提交，正在处理...', 'success');
    pollStatus(data.request_id);
  } catch(err) {
    toast(err.message, 'error');
    btn.disabled = false;
    btn.innerHTML = '<i class="fa fa-paper-plane"></i> 开始生成素材';
  }
});

async function pollStatus(requestId) {
  const resp = await fetch(`${API}/creative/status/${requestId}`);
  const data = await resp.json();
  const stage = data.stage || 'analyze';
  updateProgress(stage);

  if (stage === 'done' || data.status === 'done') {
    updateProgress('done');
    document.getElementById('submit-btn').disabled = false;
    document.getElementById('submit-btn').innerHTML = '<i class="fa fa-paper-plane"></i> 开始生成素材';
    if (data.result) showResult(data);
    if (data.error) toast(data.error, 'error');
    return;
  }
  if (stage === 'failed') {
    updateProgress('done');
    toast(data.error || '生成失败', 'error');
    document.getElementById('submit-btn').disabled = false;
    document.getElementById('submit-btn').innerHTML = '<i class="fa fa-paper-plane"></i> 开始生成素材';
    return;
  }
  pollingTimer = setTimeout(() => pollStatus(requestId), 2000);
}

function showResult(data) {
  const area = document.getElementById('result-area');
  area.classList.remove('hidden');
  area.scrollIntoView({behavior:'smooth'});
  const r = data.result;

  // 视频
  if (r.video_url) {
    document.getElementById('video-card').classList.remove('hidden');
    document.getElementById('result-video').src = r.video_url;
  }

  // 分镜
  const sb = document.getElementById('storyboard-container');
  sb.innerHTML = '';
  if (r.storyboard && r.storyboard.length) {
    r.storyboard.forEach(s => {
      sb.innerHTML += `<div class="flex gap-3 p-3 bg-gray-50 rounded-lg">
        <span class="text-xs font-mono text-primary whitespace-nowrap mt-0.5">${s.time||''}</span>
        <div><p class="text-sm font-medium">${s.scene||''}</p><p class="text-xs text-gray-500 mt-0.5">${s.copy||''}</p></div>
      </div>`;
    });
  }

  // 标题
  const tc = document.getElementById('titles-container');
  tc.innerHTML = '';
  if (r.ad_titles && r.ad_titles.length) {
    r.ad_titles.forEach(t => {
      tc.innerHTML += `<p class="text-sm text-gray-700 bg-amber-50 px-3 py-2 rounded-lg">${t}</p>`;
    });
  }

  // 人群
  const ac = document.getElementById('audience-container');
  const aud = r.suggested_audience || {};
  ac.innerHTML = Object.entries(aud).map(([k,v]) => `<span class="tag bg-green-50 text-green-700 mr-2 mb-2">${k}: ${v}</span>`).join('') || '<p class="text-sm text-gray-400">暂无定向建议</p>';

  // 质量
  const qc = document.getElementById('quality-card');
  if (data.quality) {
    qc.classList.remove('hidden');
    const q = data.quality;
    const gradeColor = {A:'text-green-600',B:'text-blue-600',C:'text-amber-600',D:'text-red-500'};
    qc.innerHTML = `<h3 class="font-bold mb-2 flex items-center gap-2"><i class="fa fa-check-circle text-green-500"></i>质量评估</h3>
      <p class="text-3xl font-bold ${gradeColor[q.grade]||'text-gray-600'}">${q.total_score||'-'} <span class="text-sm">分 / ${q.grade||'-'}</span></p>
      <div class="mt-2 text-xs text-gray-500">${Object.entries(q).filter(([k])=>!['total_score','grade'].includes(k)).map(([k,v])=>`<span class="mr-3">${k}: ${v}</span>`).join('')}</div>`;
  }

  // 合规
  const cc = document.getElementById('compliance-card');
  if (data.compliance) {
    cc.classList.remove('hidden');
    const c = data.compliance;
    const decColor = {auto_pass:'text-green-600',auto_retry:'text-amber-600',manual_review:'text-red-500'};
    cc.innerHTML = `<h3 class="font-bold mb-2 flex items-center gap-2"><i class="fa fa-shield text-blue-500"></i>合规检测</h3>
      <p class="text-xl font-bold ${decColor[c.decision]||'text-gray-600'}">${c.decision||'-'}</p>
      <p class="text-xs text-gray-500 mt-1">${c.reason||''}</p>`;
  }

  // 策略理由
  if (r.creative_rationale) {
    document.getElementById('rationale-text').textContent = r.creative_rationale;
  }
}

function resetForm() {
  document.getElementById('result-area').classList.add('hidden');
  document.getElementById('generate-form-card').classList.remove('hidden');
  document.getElementById('generate-form').reset();
  document.querySelectorAll('.stage-dot').forEach(d => { d.classList.remove('active','done'); });
}

// ═══ 页面 2：素材管理 ═══
async function loadArchive() {
  try {
    const resp = await fetch(`${API}/archive/all?limit=50`);
    const data = await resp.json();
    const grid = document.getElementById('archive-grid');
    const empty = document.getElementById('archive-empty');
    grid.innerHTML = '';

    if (!data.items || !data.items.length) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');

    data.items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'bg-white rounded-xl p-5 shadow-sm hover:shadow-md transition cursor-pointer fade-in';
      card.onclick = () => openDetail(item.id);
      const typeBadge = {
        '对比测评':'bg-blue-50 text-blue-600',
        '知识科普':'bg-green-50 text-green-600',
        '场景植入':'bg-purple-50 text-purple-600',
        '数字清单':'bg-amber-50 text-amber-600',
      };
      const badgeClass = typeBadge[item.script_type] || 'bg-gray-50 text-gray-600';
      card.innerHTML = `
        <div class="flex items-start justify-between mb-2">
          <span class="tag text-xs ${badgeClass}">${item.script_type||'未分类'}</span>
          <span class="text-xs text-gray-400">${(item.created_at||'').slice(0,10)}</span>
        </div>
        <h4 class="font-bold text-gray-800 mb-1">${item.product_name||'未命名'}</h4>
        <p class="text-sm text-gray-500 mb-3 line-clamp-2">${item.hook||''}</p>
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-400">${item.category||''}</span>
          <span>${starHTML(item.performance_star||0)}</span>
        </div>
        ${item.has_performance_data ? `<div class="mt-2 text-xs text-green-600"><i class="fa fa-check-circle"></i> 有效果数据</div>` : ''}
      `;
      grid.appendChild(card);
    });
  } catch(err) {
    toast('加载素材列表失败: '+err.message, 'error');
  }
}

async function searchArchive() {
  const query = document.getElementById('archive-search').value || '';
  const category = document.getElementById('archive-category').value;
  const script_type = document.getElementById('archive-type').value;
  const params = new URLSearchParams();
  if (query) params.set('query', query);
  if (category) params.set('category', category);
  if (script_type) params.set('script_type', script_type);
  params.set('n_results', '30');

  try {
    const resp = await fetch(`${API}/archive/search?${params}`);
    const data = await resp.json();
    const grid = document.getElementById('archive-grid');
    const empty = document.getElementById('archive-empty');
    grid.innerHTML = '';
    if (!data.items || !data.items.length) { empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    data.items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'bg-white rounded-xl p-5 shadow-sm hover:shadow-md transition cursor-pointer fade-in';
      card.onclick = () => openDetail(item.id);
      const typeBadge = {
        '对比测评':'bg-blue-50 text-blue-600',
        '知识科普':'bg-green-50 text-green-600',
        '场景植入':'bg-purple-50 text-purple-600',
        '数字清单':'bg-amber-50 text-amber-600',
      };
      const badgeClass = typeBadge[item.script_type] || 'bg-gray-50 text-gray-600';
      card.innerHTML = `
        <div class="flex items-start justify-between mb-2">
          <span class="tag text-xs ${badgeClass}">${item.script_type||'未分类'}</span>
          <span class="text-xs text-gray-400">${(item.created_at||'').slice(0,10)}</span>
        </div>
        <h4 class="font-bold text-gray-800 mb-1">${item.product_name||'未命名'}</h4>
        <p class="text-sm text-gray-500 mb-3">${item.hook||''}</p>
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-400">相似度: ${(item.similarity*100).toFixed(0)}%</span>
          <span>${starHTML(item.performance_star||0)}</span>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch(err) {
    toast('搜索失败: '+err.message, 'error');
  }
}

async function openDetail(id) {
  try {
    const resp = await fetch(`${API}/archive/${id}`);
    const item = await resp.json();
    const modal = document.getElementById('detail-modal');
    const content = document.getElementById('detail-content');
    const bundle = item.bundle || {};
    const storyboard = bundle.storyboard || [];
    const adTitles = item.ad_titles || bundle.ad_titles || [];

    content.innerHTML = `
      <h2 class="text-xl font-bold mb-1">${item.product_name||'未命名'}</h2>
      <div class="flex gap-2 mb-4">
        <span class="tag bg-indigo-50 text-primary text-xs">${item.script_type||''}</span>
        <span class="tag bg-gray-100 text-gray-600 text-xs">${item.category||''}</span>
        ${item.has_performance_data ? `<span class="text-xs text-green-600">${starHTML(item.performance_star||0)} ROI: ${item.roi||0}</span>` : ''}
      </div>
      ${item.video_url ? `<video src="${item.video_url}" controls class="w-full rounded-lg mb-4"></video>` : ''}
      <h4 class="font-bold text-sm mt-4 mb-2">钩子文案</h4>
      <p class="text-gray-700 bg-amber-50 px-3 py-2 rounded-lg">${item.hook||''}</p>
      <h4 class="font-bold text-sm mt-4 mb-2">分镜脚本</h4>
      <div class="space-y-2">${storyboard.map(s => `<div class="flex gap-3 p-2 bg-gray-50 rounded"><span class="text-xs font-mono text-primary">${s.time||''}</span><p class="text-sm">${s.scene||''}</p></div>`).join('')||'<p class="text-sm text-gray-400">无</p>'}</div>
      <h4 class="font-bold text-sm mt-4 mb-2">投放标题</h4>
      <div class="space-y-1">${adTitles.map(t => `<p class="text-sm text-gray-700">${t}</p>`).join('')||'<p class="text-sm text-gray-400">无</p>'}</div>
      ${item.has_performance_data ? `<div class="mt-4 grid grid-cols-3 gap-2 text-center">
        <div class="bg-gray-50 rounded p-2"><p class="text-xs text-gray-400">消耗</p><p class="font-bold">${(item.total_cost||0).toFixed(0)}</p></div>
        <div class="bg-gray-50 rounded p-2"><p class="text-xs text-gray-400">ROI</p><p class="font-bold text-green-600">${(item.roi||0).toFixed(2)}</p></div>
        <div class="bg-gray-50 rounded p-2"><p class="text-xs text-gray-400">CTR</p><p class="font-bold">${((item.avg_ctr||0)*100).toFixed(1)}%</p></div>
      </div>`:''}
    `;
    modal.classList.remove('hidden');
  } catch(err) {
    toast('加载详情失败: '+err.message, 'error');
  }
}

function closeDetail() {
  document.getElementById('detail-modal').classList.add('hidden');
}

async function loadCategories() {
  try {
    const resp = await fetch(`${API}/archive/categories`);
    const data = await resp.json();
    const sel = document.getElementById('archive-category');
    data.categories.forEach(c => {
      sel.innerHTML += `<option value="${c.category}">${c.category} (${c.count})</option>`;
    });
  } catch(_){}
}
loadCategories();

// ═══ 页面 3：效果反馈 ═══
async function initFeedback() {
  await loadLinkFormData();
  await loadLinks();
  await loadStrategyCategories();
}

async function loadLinkFormData() {
  try {
    const resp = await fetch(`${API}/archive/all?limit=100`);
    const data = await resp.json();
    const sel = document.getElementById('link-creative');
    sel.innerHTML = '<option value="">选择素材...</option>';
    (data.items||[]).forEach(item => {
      sel.innerHTML += `<option value="${item.id}">${item.product_name||'未命名'} - ${item.script_type||''}</option>`;
    });
    // 同步更新效果面板的选择器
    const psel = document.getElementById('perf-select');
    psel.innerHTML = '<option value="">选择已关联的素材...</option>';
  } catch(_){}
}

async function createLink() {
  const creative_id = document.getElementById('link-creative').value;
  const ad_id = document.getElementById('link-ad-id').value.trim();
  const advertiser_id = document.getElementById('link-advertiser').value.trim();
  if (!creative_id || !ad_id || !advertiser_id) return toast('请填写完整信息', 'error');

  try {
    const resp = await fetch(`${API}/feedback/link`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({creative_id, ad_id, advertiser_id, user_id:'demo_user'}),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '关联失败');
    toast('关联创建成功', 'success');
    document.getElementById('link-ad-id').value = '';
    document.getElementById('link-advertiser').value = '';
    loadLinks();
    loadPerfSelect();
  } catch(err) {
    toast(err.message, 'error');
  }
}

async function loadLinks() {
  try {
    const resp = await fetch(`${API}/feedback/links?user_id=demo_user`);
    const data = await resp.json();
    const tbody = document.getElementById('links-table');
    const empty = document.getElementById('links-empty');
    tbody.innerHTML = '';
    if (!data.items || !data.items.length) { empty.style.display = 'block'; return; }
    empty.style.display = 'none';
    data.items.forEach(item => {
      tbody.innerHTML += `<tr class="border-b">
        <td class="py-2">${item.product_name||item.creative_id}</td>
        <td class="py-2 font-mono text-xs">${item.ad_id}</td>
        <td class="py-2 text-xs text-gray-500">${(item.linked_at||'').slice(0,10)}</td>
        <td class="py-2">${starHTML(item.performance_star||0)}</td>
        <td class="py-2">
          <button onclick="deleteLink('${item.creative_id}','${item.ad_id}')" class="text-xs text-red-400 hover:text-red-600"><i class="fa fa-trash"></i></button>
        </td>
      </tr>`;
    });
    loadPerfSelect();
  } catch(err) {
    toast('加载关联列表失败: '+err.message, 'error');
  }
}

async function deleteLink(creative_id, ad_id) {
  if (!confirm('确认取消此关联？')) return;
  try {
    await fetch(`${API}/feedback/link`, {
      method: 'DELETE',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({creative_id, ad_id}),
    });
    toast('已取消关联', 'success');
    loadLinks();
  } catch(err) {
    toast(err.message, 'error');
  }
}

async function loadPerfSelect() {
  try {
    const resp = await fetch(`${API}/feedback/links?user_id=demo_user`);
    const data = await resp.json();
    const sel = document.getElementById('perf-select');
    sel.innerHTML = '<option value="">选择已关联的素材...</option>';
    (data.items||[]).forEach(item => {
      sel.innerHTML += `<option value="${item.creative_id}|${item.ad_id}">${item.product_name||item.creative_id} - ${item.ad_id}</option>`;
    });
  } catch(_){}
}

let perfChart = null;

async function loadPerformance() {
  const val = document.getElementById('perf-select').value;
  if (!val) return;
  const [creative_id, ad_id] = val.split('|');
  const panel = document.getElementById('perf-panel');

  try {
    const [perfResp, summaryResp] = await Promise.all([
      fetch(`${API}/feedback/performance/${creative_id}?ad_id=${ad_id}`),
      fetch(`${API}/feedback/summary/${creative_id}?ad_id=${ad_id}`),
    ]);
    const perfData = await perfResp.json();
    const summaryData = await summaryResp.json();

    panel.classList.remove('hidden');
    const s = summaryData.data || {};

    document.getElementById('perf-summary').innerHTML = [
      {label:'消耗', value:`${(s.total_cost||0).toFixed(0)}元`},
      {label:'展示', value:`${(s.total_impressions||0).toLocaleString()}`},
      {label:'ROI', value:`${(s.avg_roi||0).toFixed(2)}`},
      {label:'CTR', value:`${((s.avg_ctr||0)*100).toFixed(1)}%`},
      {label:'CVR', value:`${((s.avg_cvr||0)*100).toFixed(2)}%`},
      {label:'完播率', value:`${((s.avg_completion||0)*100).toFixed(1)}%`},
      {label:'订单', value:`${s.total_orders||0}`},
      {label:'星级', value:starHTML(s.performance_star||0)},
    ].map(m => `<div class="bg-gray-50 rounded-lg p-3"><p class="text-xs text-gray-400">${m.label}</p><p class="font-bold text-sm mt-0.5">${m.value}</p></div>`).join('');

    // 图表
    const days = perfData.data || [];
    const ctx = document.getElementById('perf-chart').getContext('2d');
    if (perfChart) perfChart.destroy();
    perfChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: days.map(d => d.date),
        datasets: [
          { label: 'CTR', data: days.map(d => d.ctr*100), borderColor: '#6366f1', tension: 0.3, yAxisID: 'y' },
          { label: 'ROI', data: days.map(d => d.roi), borderColor: '#f59e0b', tension: 0.3, yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          y: { type:'linear', position:'left', title:{display:true,text:'CTR (%)'}, ticks:{callback:v=>v.toFixed(1)+'%'} },
          y1: { type:'linear', position:'right', title:{display:true,text:'ROI'}, grid:{drawOnChartArea:false} },
        },
      },
    });
  } catch(err) {
    toast('加载效果数据失败: '+err.message, 'error');
  }
}

async function loadStrategyCategories() {
  try {
    const resp = await fetch(`${API}/archive/categories`);
    const data = await resp.json();
    const sel = document.getElementById('strategy-category');
    data.categories.forEach(c => {
      sel.innerHTML += `<option value="${c.category}">${c.category} (${c.count})</option>`;
    });
  } catch(_){}
}

async function loadStrategy() {
  const category = document.getElementById('strategy-category').value;
  if (!category) return toast('请选择品类', 'error');
  try {
    const [compResp, insightResp] = await Promise.all([
      fetch(`${API}/strategy/comparison?category=${encodeURIComponent(category)}`),
      fetch(`${API}/strategy/insight?category=${encodeURIComponent(category)}`),
    ]);
    const comp = await compResp.json();
    const insight = await insightResp.json();

    const items = comp.items || [];
    const table = document.getElementById('strategy-table');
    if (items.length === 0) {
      table.innerHTML = '<p class="text-sm text-gray-400">暂无该品类的效果数据</p>';
    } else {
      table.innerHTML = `<table class="w-full text-sm">
        <thead><tr class="text-left text-gray-500 border-b">
          <th class="pb-2">创意类型</th><th class="pb-2">钩子类型</th><th class="pb-2">样本数</th>
          <th class="pb-2">平均 CTR</th><th class="pb-2">平均 ROI</th><th class="pb-2">完成率</th>
        </tr></thead>
        <tbody>${items.map(i => `<tr class="border-b">
          <td class="py-2 font-medium">${i.script_type}</td>
          <td class="py-2">${i.hook_type}</td>
          <td class="py-2">${i.sample_count}</td>
          <td class="py-2">${((i.avg_ctr||0)*100).toFixed(1)}%</td>
          <td class="py-2 font-bold ${(i.avg_roi||0)>=2?'text-green-600':''}">${(i.avg_roi||0).toFixed(2)}</td>
          <td class="py-2">${((i.avg_completion||0)*100).toFixed(1)}%</td>
        </tr>`).join('')}</tbody></table>`;
    }
    document.getElementById('strategy-insight').innerHTML = `<i class="fa fa-lightbulb-o mr-1"></i>${insight.insight||'暂无洞察数据'}`;
  } catch(err) {
    toast('加载策略数据失败: '+err.message, 'error');
  }
}