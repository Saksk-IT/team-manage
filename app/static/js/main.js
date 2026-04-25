/**
 * GPT Team 管理系统 - 通用 JavaScript
 */

// Toast 提示函数
const TEAM_TYPE_STANDARD = 'standard';
const TEAM_TYPE_WARRANTY = 'warranty';
let currentImportTeamType = TEAM_TYPE_STANDARD;

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;

    let icon = 'info';
    if (type === 'success') icon = 'check-circle';
    if (type === 'error') icon = 'alert-circle';

    toast.innerHTML = `<i data-lucide="${icon}"></i><span>${message}</span>`;
    toast.className = `toast ${type} show`;

    if (window.lucide) {
        lucide.createIcons();
    }

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// 日期格式化函数
function formatDateTime(dateString) {
    if (!dateString) return '-';

    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) {
        return '';
    }

    return String(unsafe)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}


function isImportOnlyPage() {
    return window.location.pathname === '/admin/import-only';
}

function getImportModeMeta(teamType = TEAM_TYPE_STANDARD) {
    if (teamType === TEAM_TYPE_WARRANTY) {
        return {
            modalTitle: '导入质保 Team',
            singleHelper: '质保 Team 不会生成兑换码，也不会参与普通兑换或库存统计。',
            batchHelper: '支持粘贴一行一个 AT Token，也支持直接粘贴完整的多个 Team 账号 JSON。导入后的质保 Team 不会生成兑换码。',
            singleResultTitle: '导入结果',
            batchCodesTitle: '质保 Team 不生成兑换码'
        };
    }

    if (isImportOnlyPage()) {
        return {
            modalTitle: '导入 Team',
            singleHelper: '子管理员导入后不会生成兑换码；账号会进入待分类池，由总管理员决定进入控制台或质保 Team。若进入控制台，再由总管理员选择普通或质保兑换码。',
            batchHelper: '支持粘贴一行一个 AT Token，也支持完整 JSON。导入后进入待分类池，不生成兑换码。',
            singleResultTitle: '导入结果',
            batchCodesTitle: '待分类导入结果'
        };
    }

    return {
        modalTitle: '导入 Team',
        singleHelper: '导入后会按系统设置中的每个 Team 默认最大人数，自动根据实际剩余席位生成同数量的绑定兑换码；可选择生成普通码或质保码。',
        batchHelper: '支持粘贴一行一个 AT Token，也支持直接粘贴完整的多个 Team 账号 JSON，系统会自动提取 Access Token (AT)；可选择生成普通码或质保码。',
        singleResultTitle: '自动生成的绑定兑换码',
        batchCodesTitle: '自动生成的绑定兑换码'
    };
}

function getImportGeneratedCodesTitle(teamType = TEAM_TYPE_STANDARD, generateWarrantyCodes = false) {
    if (isImportOnlyPage()) {
        return '导入结果';
    }

    if (teamType === TEAM_TYPE_WARRANTY) {
        return '质保 Team 不生成兑换码';
    }

    return generateWarrantyCodes ? '自动生成的质保绑定兑换码' : '自动生成的绑定兑换码';
}

function setImportWarrantyOptionsVisibility(teamType = TEAM_TYPE_STANDARD) {
    const isStandardTeam = teamType === TEAM_TYPE_STANDARD && !isImportOnlyPage();
    const optionIds = ['singleImportWarrantyOptions', 'batchImportWarrantyOptions'];
    const groupIds = ['single-import-warranty-days-group', 'batch-import-warranty-days-group'];
    const hiddenInputIds = ['singleImportGenerateWarrantyCodes', 'batchImportGenerateWarrantyCodes'];
    const checkboxSelectors = [
        '#singleImportForm input[name="generateWarrantyCodesCheckbox"]',
        '#batchImportForm input[name="generateWarrantyCodesCheckbox"]',
    ];

    optionIds.forEach((id) => {
        const element = document.getElementById(id);
        if (element) {
            element.style.display = isStandardTeam ? 'block' : 'none';
        }
    });

    checkboxSelectors.forEach((selector, index) => {
        const checkbox = document.querySelector(selector);
        const hiddenInput = document.getElementById(hiddenInputIds[index]);
        const group = document.getElementById(groupIds[index]);
        const checked = isStandardTeam ? Boolean(checkbox?.checked) : false;

        if (checkbox && !isStandardTeam) {
            checkbox.checked = false;
        }

        if (hiddenInput) {
            hiddenInput.value = checked ? 'true' : 'false';
        }

        if (group) {
            group.style.display = checked ? 'block' : 'none';
        }
    });

    updateImportGeneratedCodeTitles(teamType);
}

function updateImportGeneratedCodeTitles(teamType = TEAM_TYPE_STANDARD) {
    const singleTitle = document.getElementById('singleImportResultTitle');
    const batchTitle = document.getElementById('batchImportCodesTitle');
    const singleWarrantyChecked = Boolean(document.querySelector('#singleImportForm input[name="generateWarrantyCodesCheckbox"]')?.checked);
    const batchWarrantyChecked = Boolean(document.querySelector('#batchImportForm input[name="generateWarrantyCodesCheckbox"]')?.checked);

    if (singleTitle) {
        singleTitle.textContent = getImportGeneratedCodesTitle(teamType, singleWarrantyChecked);
    }

    if (batchTitle) {
        batchTitle.textContent = getImportGeneratedCodesTitle(teamType, batchWarrantyChecked);
    }
}

function handleImportWarrantyToggle(checkbox, hiddenInputId, daysGroupId, teamTypeInputId) {
    const hiddenInput = document.getElementById(hiddenInputId);
    const teamType = document.getElementById(teamTypeInputId)?.value || currentImportTeamType;
    if (hiddenInput) {
        hiddenInput.value = checkbox.checked ? 'true' : 'false';
    }
    toggleWarrantyDays(checkbox, daysGroupId);
    updateImportGeneratedCodeTitles(teamType);
}

function setWarrantyDaysQuickValue(control, days) {
    const normalizedDays = parseInt(days, 10);
    if (!Number.isInteger(normalizedDays) || normalizedDays < 1) {
        return;
    }

    const group = control?.closest?.('.form-group');
    const input = group?.querySelector?.('input[name="warrantyDays"]');
    if (!input) {
        return;
    }

    input.value = normalizedDays;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

function showImportTeamModal(teamType = TEAM_TYPE_STANDARD) {
    currentImportTeamType = teamType === TEAM_TYPE_WARRANTY ? TEAM_TYPE_WARRANTY : TEAM_TYPE_STANDARD;
    const meta = getImportModeMeta(currentImportTeamType);
    const initialTabId = isImportOnlyPage() ? 'batchImport' : 'singleImport';

    const singleTeamTypeInput = document.getElementById('singleImportTeamType');
    const batchTeamTypeInput = document.getElementById('batchImportTeamType');
    const modalTitle = document.getElementById('importTeamModalTitle');
    const singleHelperText = document.getElementById('singleImportHelperText');
    const batchHelperText = document.getElementById('batchImportHelperText');
    const singleResultTitle = document.getElementById('singleImportResultTitle');
    const batchCodesTitle = document.getElementById('batchImportCodesTitle');
    const singleResult = document.getElementById('singleImportResult');
    const batchResultsContainer = document.getElementById('batchResultsContainer');
    const batchProgressContainer = document.getElementById('batchProgressContainer');

    if (singleTeamTypeInput) singleTeamTypeInput.value = currentImportTeamType;
    if (batchTeamTypeInput) batchTeamTypeInput.value = currentImportTeamType;
    if (modalTitle) modalTitle.textContent = meta.modalTitle;
    if (singleHelperText) singleHelperText.textContent = meta.singleHelper;
    if (batchHelperText) batchHelperText.textContent = meta.batchHelper;
    if (singleResultTitle) singleResultTitle.textContent = meta.singleResultTitle;
    if (batchCodesTitle) batchCodesTitle.textContent = meta.batchCodesTitle;
    if (singleResult) singleResult.style.display = 'none';
    if (batchResultsContainer) batchResultsContainer.style.display = 'none';
    if (batchProgressContainer) batchProgressContainer.style.display = 'none';

    setImportWarrantyOptionsVisibility(currentImportTeamType);
    updateBatchImportCodes([], currentImportTeamType, false);
    switchModalTab('importTeamModal', initialTabId);
    showModal('importTeamModal');
}

function renderImportedTeamsSummary(importedTeams = [], teamType = TEAM_TYPE_STANDARD, generateWarrantyCodes = false) {
    if (!importedTeams.length) {
        if (isImportOnlyPage()) {
            return '<div class="text-muted">本次导入已进入待分类池，等待总管理员决定去向。</div>';
        }
        return teamType === TEAM_TYPE_WARRANTY
            ? '<div class="text-muted">本次导入的质保 Team 不会生成兑换码。</div>'
            : `<div class="text-muted">本次未生成${generateWarrantyCodes ? '质保' : ''}绑定兑换码。</div>`;
    }

    return importedTeams.map(team => `
        <div style="padding: 0.75rem 0; border-bottom: 1px solid rgba(255,255,255,0.06);">
            <div style="font-weight: 600; margin-bottom: 0.25rem;">
                ${escapeHtml(team.team_name || `Team ${team.team_id}`)} <span style="color: var(--text-muted);">#${team.team_id}</span>
            </div>
            <div style="font-size: 0.875rem; color: var(--text-muted); line-height: 1.6;">
                当前成员 ${team.current_members}/${team.max_members}，剩余席位 ${team.remaining_seats}，
                ${isImportOnlyPage()
            ? '已进入待分类池，等待总管理员选择进入控制台或质保 Team'
            : (teamType === TEAM_TYPE_WARRANTY
                ? '质保 Team 不生成兑换码'
                : `自动生成 ${team.generated_code_count} 个${(team.generated_code_has_warranty ?? generateWarrantyCodes) ? '质保绑定兑换码' : '绑定兑换码'}`)}
            </div>
        </div>
    `).join('');
}

function collectImportedCodes(importedTeams = []) {
    return importedTeams.flatMap(team => Array.isArray(team.generated_codes) ? team.generated_codes : []);
}

function showSingleImportResult(importedTeams = [], teamType = TEAM_TYPE_STANDARD, generateWarrantyCodes = false) {
    const resultBox = document.getElementById('singleImportResult');
    const summaryBox = document.getElementById('singleImportSummary');
    const codesBox = document.getElementById('singleImportCodes');
    const copyBtn = document.getElementById('singleImportCopyBtn');
    const titleBox = document.getElementById('singleImportResultTitle');

    if (!resultBox || !summaryBox || !codesBox || !copyBtn || !titleBox) {
        return;
    }

    const codes = collectImportedCodes(importedTeams);
    titleBox.textContent = getImportGeneratedCodesTitle(teamType, generateWarrantyCodes);
    summaryBox.innerHTML = renderImportedTeamsSummary(importedTeams, teamType, generateWarrantyCodes);
    codesBox.value = codes.join('\n');
    const hasCodes = codes.length > 0;
    codesBox.style.display = hasCodes ? 'block' : 'none';
    copyBtn.style.display = hasCodes ? 'inline-flex' : 'none';
    resultBox.style.display = 'block';
}

async function copySingleImportCodes() {
    const codesBox = document.getElementById('singleImportCodes');
    if (!codesBox || !codesBox.value.trim()) {
        showToast('暂无可复制的兑换码', 'error');
        return;
    }

    await copyToClipboard(codesBox.value.trim());
}

function updateBatchImportCodes(codes = [], teamType = TEAM_TYPE_STANDARD, generateWarrantyCodes = false) {
    const codesSection = document.getElementById('batchImportCodesSection');
    const codesSummary = document.getElementById('batchImportCodesSummary');
    const codesBox = document.getElementById('batchImportCodes');
    const copyBtn = document.getElementById('batchImportCodesCopyBtn');
    const titleBox = document.getElementById('batchImportCodesTitle');

    if (!codesSection || !codesSummary || !codesBox || !copyBtn || !titleBox) {
        return;
    }

    const normalizedCodes = Array.from(new Set((codes || []).filter(Boolean)));
    codesBox.value = normalizedCodes.join('\n');
    titleBox.textContent = getImportGeneratedCodesTitle(teamType, generateWarrantyCodes);

    if (normalizedCodes.length > 0) {
        codesSection.style.display = 'block';
        codesSummary.textContent = `已自动汇总 ${normalizedCodes.length} 个${generateWarrantyCodes ? '质保' : ''}绑定兑换码`;
        copyBtn.style.display = 'inline-flex';
    } else {
        codesSection.style.display = 'none';
        codesSummary.textContent = teamType === TEAM_TYPE_WARRANTY ? '质保 Team 不会生成兑换码' : `导入成功后会自动汇总${generateWarrantyCodes ? '质保' : ''}绑定兑换码`;
        copyBtn.style.display = teamType === TEAM_TYPE_WARRANTY ? 'none' : 'inline-flex';
    }
}

function buildForcedRefreshUrl() {
    const url = new URL(window.location.href);
    url.searchParams.set('_refresh', Date.now().toString());
    return url.toString();
}

function refreshAdminListView(delayMs = 0, modalIds = []) {
    const pathname = window.location.pathname || '';
    const normalizedPathname = pathname.replace(/\/+$/, '') || '/';
    const shouldRefresh =
        normalizedPathname === '/admin' ||
        normalizedPathname === '/admin/warranty-teams' ||
        normalizedPathname === '/admin/codes';

    if (!shouldRefresh) {
        return;
    }

    const executeRefresh = () => {
        modalIds.forEach(modalId => hideModal(modalId));
        window.location.replace(buildForcedRefreshUrl());
    };

    if (delayMs > 0) {
        setTimeout(executeRefresh, delayMs);
    } else {
        executeRefresh();
    }
}

function scheduleImportedTeamListRefresh(delayMs = 1500) {
    refreshAdminListView(delayMs, ['importTeamModal']);
}

async function copyBatchImportCodes() {
    const codesBox = document.getElementById('batchImportCodes');
    if (!codesBox || !codesBox.value.trim()) {
        showToast('暂无可复制的兑换码', 'error');
        return;
    }

    await copyToClipboard(codesBox.value.trim());
}

// 登出函数
async function logout() {
    const confirmed = await showSystemConfirm({
        title: '确认登出',
        message: '确定要登出吗？',
        confirmText: '登出',
    });
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch('/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (response.ok && data.success) {
            window.location.href = '/login';
        } else {
            showToast('登出失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    }
}

// API 调用封装
async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || data.detail || '请求失败');
        }

        return { success: true, data };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

// 确认对话框
function confirmAction(message, options = {}) {
    return showSystemConfirm({
        message,
        ...options,
    });
}

function applyDensityMode(mode) {
    const isCompact = mode === 'compact';
    document.body.classList.toggle('compact-mode', isCompact);

    const btn = document.getElementById('densityToggleBtn');
    if (btn) {
        btn.innerHTML = isCompact
            ? '<i data-lucide="panel-top-close" style="width: 14px; height: 14px;"></i> 舒展模式'
            : '<i data-lucide="panel-top-open" style="width: 14px; height: 14px;"></i> 紧凑模式';
    }

    if (window.lucide) {
        lucide.createIcons();
    }
}

function initDensityMode() {
    if (!document.body.classList.contains('admin-shell')) {
        return;
    }

    const savedMode = localStorage.getItem('admin_density_mode') || 'comfortable';
    applyDensityMode(savedMode);
}

function toggleDensityMode() {
    const nextMode = document.body.classList.contains('compact-mode') ? 'comfortable' : 'compact';
    localStorage.setItem('admin_density_mode', nextMode);
    applyDensityMode(nextMode);
}

// 页面加载完成后执行
document.addEventListener('DOMContentLoaded', function () {
    // 检查认证状态
    checkAuthStatus();
    initDensityMode();
});

// 检查认证状态
async function checkAuthStatus() {
    // 如果在登录页面,跳过检查
    if (window.location.pathname === '/login') {
        return;
    }

    try {
        const response = await fetch('/auth/status');
        const data = await response.json();

        if (!data.authenticated && window.location.pathname.startsWith('/admin')) {
            // 未登录且在管理员页面,跳转到登录页
            window.location.href = '/login';
        }
    } catch (error) {
        console.error('检查认证状态失败:', error);
    }
}

// === 模态框控制逻辑 ===

function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden'; // 防止背景滚动
    }
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
    }
}

function switchModalTab(modalId, tabId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    // 切换按钮状态
    const tabs = modal.querySelectorAll('.modal-tab-btn');
    tabs.forEach(tab => {
        if (tab.getAttribute('onclick').includes(`'${tabId}'`)) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    // 切换面板显示
    const panels = modal.querySelectorAll('.import-panel, .card-body');
    panels.forEach(panel => {
        if (panel.id === tabId) {
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    });
}

/**
 * 切换质保时长输入框的显示
 */
function toggleWarrantyDays(checkbox, targetId) {
    const target = document.getElementById(targetId);
    if (target) {
        target.style.display = checkbox.checked ? 'block' : 'none';
    }
}

// === Team 导入逻辑 ===

async function handleSingleImport(event) {
    event.preventDefault();
    const form = event.target;
    const teamType = form.teamType?.value || currentImportTeamType;
    const generateWarrantyCodes = teamType === TEAM_TYPE_STANDARD && Boolean(form.generateWarrantyCodesCheckbox?.checked);
    const warrantyDays = form.warrantyDays ? parseInt(form.warrantyDays.value || '30', 10) : 30;
    const accessToken = form.accessToken.value.trim();
    const refreshToken = form.refreshToken ? form.refreshToken.value.trim() : null;
    const sessionToken = form.sessionToken ? form.sessionToken.value.trim() : null;
    const clientId = form.clientId ? form.clientId.value.trim() : null;
    const email = form.email.value.trim();
    const accountId = form.accountId.value.trim();
    const submitButton = form.querySelector('button[type="submit"]');

    submitButton.disabled = true;
    submitButton.textContent = '导入中...';

    try {
        const result = await apiCall('/admin/teams/import', {
            method: 'POST',
            body: JSON.stringify({
                import_type: 'single',
                team_type: teamType,
                access_token: accessToken,
                refresh_token: refreshToken || null,
                session_token: sessionToken || null,
                client_id: clientId || null,
                email: email || null,
                account_id: accountId || null,
                generate_warranty_codes: generateWarrantyCodes,
                warranty_days: warrantyDays,
            })
        });

        if (result.success) {
            const importedTeams = result.data.imported_teams || [];
            const generatedCodeCount = result.data.generated_code_count || 0;
            showSingleImportResult(importedTeams, teamType, generateWarrantyCodes);
            if (isImportOnlyPage()) {
                showToast('Team 导入成功，已进入待分类池，等待总管理员分类', 'success');
            } else if (teamType === TEAM_TYPE_WARRANTY) {
                showToast('质保 Team 导入成功', 'success');
            } else {
                showToast(`Team 导入成功，已自动生成 ${generatedCodeCount} 个${generateWarrantyCodes ? '质保' : ''}绑定兑换码`, 'success');
            }
            form.reset();
            if (form.teamType) form.teamType.value = teamType;
            setImportWarrantyOptionsVisibility(teamType);
            scheduleImportedTeamListRefresh(1500);
        } else {
            showToast(result.error || '导入失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = '导入';
    }
}

async function handleBatchImport(event) {
    event.preventDefault();
    const form = event.target;
    const teamType = form.teamType?.value || currentImportTeamType;
    const generateWarrantyCodes = teamType === TEAM_TYPE_STANDARD && Boolean(form.generateWarrantyCodesCheckbox?.checked);
    const warrantyDays = form.warrantyDays ? parseInt(form.warrantyDays.value || '30', 10) : 30;
    const batchContent = form.batchContent.value.trim();
    const submitButton = form.querySelector('button[type="submit"]');
    const importedCodes = [];

    // UI 元素
    const progressContainer = document.getElementById('batchProgressContainer');
    const progressBar = document.getElementById('batchProgressBar');
    const progressStage = document.getElementById('batchProgressStage');
    const progressPercent = document.getElementById('batchProgressPercent');
    const successCountEl = document.getElementById('batchSuccessCount');
    const failedCountEl = document.getElementById('batchFailedCount');
    const resultsContainer = document.getElementById('batchResultsContainer');
    const resultsDiv = document.getElementById('batchResults');
    const finalSummaryEl = document.getElementById('batchFinalSummary');

    // 重置 UI
    progressContainer.style.display = 'block';
    resultsContainer.style.display = 'none';
    progressBar.style.width = '0%';
    progressStage.textContent = '准备导入...';
    progressPercent.textContent = '0%';
    successCountEl.textContent = '0';
    failedCountEl.textContent = '0';
    resultsDiv.innerHTML = '<table class="data-table"><thead><tr><th>邮箱</th><th>状态</th><th>消息</th></tr></thead><tbody id="batchResultsBody"></tbody></table>';
    updateBatchImportCodes([], teamType, generateWarrantyCodes);
    const resultsBody = document.getElementById('batchResultsBody');

    submitButton.disabled = true;
    submitButton.textContent = '导入中...';

    try {
        const response = await fetch('/admin/teams/import', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                import_type: 'batch',
                team_type: teamType,
                content: batchContent,
                generate_warranty_codes: generateWarrantyCodes,
                warranty_days: warrantyDays,
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || errorData.detail || '请求失败');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // 最后一个可能是残缺的

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);

                    if (data.type === 'start') {
                        progressStage.textContent = `开始导入 (共 ${data.total} 条)...`;
                    } else if (data.type === 'progress') {
                        const percent = Math.round((data.current / data.total) * 100);
                        progressBar.style.width = `${percent}%`;
                        progressPercent.textContent = `${percent}%`;
                        progressStage.textContent = `正在导入 ${data.current}/${data.total}...`;
                        successCountEl.textContent = data.success_count;
                        failedCountEl.textContent = data.failed_count;

                        // 实时添加到详情列表
                        if (data.last_result) {
                            resultsContainer.style.display = 'block';
                            const res = data.last_result;
                            const statusClass = res.success ? 'text-success' : 'text-danger';
                            const statusText = res.success ? '成功' : '失败';
                            const latestImportedCodes = res.success ? collectImportedCodes(res.imported_teams || []) : [];
                            if (latestImportedCodes.length) {
                                importedCodes.push(...latestImportedCodes);
                                updateBatchImportCodes(importedCodes, teamType, generateWarrantyCodes);
                            }
                            const detailsHtml = res.success && Array.isArray(res.imported_teams) && res.imported_teams.length
                                ? `
                                    <div style="margin-top: 0.5rem; font-size: 0.875rem; line-height: 1.6;">
                                        ${res.imported_teams.map(team => `
                                            <div style="margin-bottom: 0.5rem;">
                                                <strong>${escapeHtml(team.team_name || `Team ${team.team_id}`)}</strong>
                                                <span style="color: var(--text-muted);">#${team.team_id}</span>
                                                ：剩余 ${team.remaining_seats} 席，
                                                ${isImportOnlyPage()
                                                    ? '已进入待分类池，等待总管理员决定去向和兑换码类型'
                                                    : (teamType === TEAM_TYPE_WARRANTY
                                                        ? '质保 Team 不生成兑换码'
                                                        : `已生成 ${team.generated_code_count} 个${(team.generated_code_has_warranty ?? generateWarrantyCodes) ? '质保绑定码' : '绑定码'}${(team.generated_code_has_warranty ?? generateWarrantyCodes) ? `（${team.generated_code_warranty_days || warrantyDays} 天）` : ''}`)}
                                                ${team.generated_codes && team.generated_codes.length ? `
                                                    <div style="margin-top: 0.25rem; word-break: break-all;">
                                                        <code>${escapeHtml(team.generated_codes.join(', '))}</code>
                                                    </div>
                                                ` : ''}
                                            </div>
                                        `).join('')}
                                    </div>
                                `
                                : '';

                            const row = document.createElement('tr');
                            row.innerHTML = `
                                <td>${escapeHtml(res.email)}</td>
                                <td class="${statusClass}">${statusText}</td>
                                <td>
                                    <div>${escapeHtml(res.success ? (res.message || '导入成功') : (res.error || '导入失败'))}</div>
                                    ${detailsHtml}
                                </td>
                            `;
                            // 插入到最前面，方便看到最新的
                            resultsBody.insertBefore(row, resultsBody.firstChild);
                        }
                    } else if (data.type === 'finish') {
                        progressStage.textContent = '导入完成';
                        progressBar.style.width = '100%';
                        progressPercent.textContent = '100%';
                        finalSummaryEl.textContent = `总数: ${data.total} | 成功: ${data.success_count} | 失败: ${data.failed_count}`;

                        if (data.failed_count === 0 && isImportOnlyPage()) {
                            showToast('全部导入成功，已进入待分类池，等待总管理员分类', 'success');
                        } else if (data.failed_count === 0 && teamType === TEAM_TYPE_WARRANTY) {
                            showToast('质保 Team 全部导入成功', 'success');
                        } else if (data.failed_count === 0) {
                            showToast(`全部导入成功，自动生成的${generateWarrantyCodes ? '质保' : ''}绑定兑换码已显示在明细中`, 'success');
                        } else {
                            const prefix = teamType === TEAM_TYPE_WARRANTY ? '质保 Team 导入完成' : '导入完成';
                            showToast(`${prefix}，成功 ${data.success_count} 条，失败 ${data.failed_count} 条`, 'warning');
                        }
                        if (data.success_count > 0) {
                            scheduleImportedTeamListRefresh(data.failed_count === 0 ? 1500 : 2500);
                        }
                    } else if (data.type === 'error') {
                        showToast(data.error, 'error');
                    }
                } catch (e) {
                    console.error('解析流数据失败:', e, line);
                }
            }
        }
    } catch (error) {
        showToast(error.message || '网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = '批量导入';
    }
}

// === 兑换码生成逻辑 ===

async function generateSingle(event) {
    event.preventDefault();
    const form = event.target;
    const customCode = form.customCode.value.trim();
    const expiresDays = form.expiresDays.value;
    const hasWarranty = form.hasWarranty.checked;
    const warrantyDays = form.warrantyDays ? form.warrantyDays.value : 30;

    const data = {
        type: 'single',
        has_warranty: hasWarranty,
        warranty_days: parseInt(warrantyDays || 30)
    };
    if (customCode) data.code = customCode;
    if (expiresDays) data.expires_days = parseInt(expiresDays);

    const result = await apiCall('/admin/codes/generate', {
        method: 'POST',
        body: JSON.stringify(data)
    });

    if (result.success) {
        document.getElementById('generatedCode').textContent = result.data.code;
        document.getElementById('singleResult').style.display = 'block';
        form.reset();
        showToast('兑换码生成成功', 'success');
        // 如果在列表中，延迟刷新
        if (window.location.pathname === '/admin/codes') {
            setTimeout(() => location.reload(), 2000);
        }
    } else {
        showToast(result.error || '生成失败', 'error');
    }
}

async function generateBatch(event) {
    event.preventDefault();
    const form = event.target;
    const count = parseInt(form.count.value);
    const expiresDays = form.expiresDays.value;
    const hasWarranty = form.hasWarranty.checked;
    const warrantyDays = form.warrantyDays ? form.warrantyDays.value : 30;

    if (count < 1 || count > 1000) {
        showToast('生成数量必须在1-1000之间', 'error');
        return;
    }

    const data = {
        type: 'batch',
        count: count,
        has_warranty: hasWarranty,
        warranty_days: parseInt(warrantyDays || 30)
    };
    if (expiresDays) data.expires_days = parseInt(expiresDays);

    const result = await apiCall('/admin/codes/generate', {
        method: 'POST',
        body: JSON.stringify(data)
    });

    if (result.success) {
        document.getElementById('batchTotal').textContent = result.data.total;
        document.getElementById('batchCodes').value = result.data.codes.join('\n');
        document.getElementById('batchResult').style.display = 'block';
        form.reset();
        showToast(`成功生成 ${result.data.total} 个兑换码`, 'success');
        if (window.location.pathname === '/admin/codes') {
            setTimeout(() => location.reload(), 3000);
        }
    } else {
        showToast(result.error || '生成失败', 'error');
    }
}

// 统一复制到剪贴板函数
async function copyToClipboard(text) {
    if (!text) return;

    try {
        // 尝试使用 Modern Clipboard API
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            showToast('已复制到剪贴板', 'success');
            return true;
        }
    } catch (err) {
        console.error('Modern copy failed:', err);
    }

    // Fallback: 使用 textarea 方式
    try {
        const textArea = document.createElement("textarea");
        textArea.value = text;

        // 确保 textarea 不可见且不影响布局
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);

        textArea.focus();
        textArea.select();

        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);

        if (successful) {
            showToast('已复制到剪贴板', 'success');
            return true;
        }
    } catch (err) {
        console.error('Fallback copy failed:', err);
    }

    showToast('复制失败', 'error');
    return false;
}

// === 辅助函数 ===

function copyCode(code) {
    // 如果没有传入 code，尝试从生成结果中获取
    if (!code) {
        const generatedCodeEl = document.getElementById('generatedCode');
        code = generatedCodeEl ? generatedCodeEl.textContent : '';
    }

    if (code) {
        copyToClipboard(code);
    } else {
        showToast('无内容可复制', 'error');
    }
}

function copyBatchCodes() {
    const codes = document.getElementById('batchCodes').value;
    copyToClipboard(codes);
}

function downloadCodes() {
    const codes = document.getElementById('batchCodes').value;
    const blob = new Blob([codes], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `redemption_codes_${new Date().getTime()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('下载成功', 'success');
}
// === 成员管理逻辑 ===

async function viewMembers(teamId, teamEmail = '') {
    window.currentTeamId = teamId;
    const modal = document.getElementById('manageMembersModal');
    if (!modal) return;

    // 设置基本信息
    document.getElementById('modalTeamEmail').textContent = teamEmail;

    // 打开模态框
    showModal('manageMembersModal');

    // 加载成员列表
    await loadModalMemberList(teamId);
}

async function loadModalMemberList(teamId) {
    const joinedTableBody = document.getElementById('modalJoinedMembersTableBody');
    const invitedTableBody = document.getElementById('modalInvitedMembersTableBody');

    if (joinedTableBody) joinedTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">加载中...</td></tr>';
    if (invitedTableBody) invitedTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">加载中...</td></tr>';

    try {
        const result = await apiCall(`/admin/teams/${teamId}/members/list`);
        if (result.success) {
            const allMembers = result.data.members || [];
            const joinedMembers = allMembers.filter(m => m.status === 'joined');
            const invitedMembers = allMembers.filter(m => m.status === 'invited');

            // 渲染已加入成员
            if (joinedTableBody) {
                if (joinedMembers.length === 0) {
                    joinedTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">暂无已加入成员</td></tr>';
                } else {
                    joinedTableBody.innerHTML = joinedMembers.map(m => `
                        <tr>
                            <td>${m.email}</td>
                            <td>
                                <span class="role-badge role-${m.role}">
                                    ${m.role === 'account-owner' ? '所有者' : '成员'}
                                </span>
                            </td>
                            <td>${formatDateTime(m.added_at)}</td>
                            <td style="text-align: right;">
                                ${m.role !== 'account-owner' ? `
                                    <button onclick="deleteMember('${teamId}', '${m.user_id}', '${m.email}', true)" class="btn btn-sm btn-danger">
                                        <i data-lucide="trash-2"></i> 删除
                                    </button>
                                ` : '<span class="text-muted">不可删除</span>'}
                            </td>
                        </tr>
                    `).join('');
                }
            }

            // 渲染待加入成员
            if (invitedTableBody) {
                if (invitedMembers.length === 0) {
                    invitedTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">暂无待加入成员</td></tr>';
                } else {
                    invitedTableBody.innerHTML = invitedMembers.map(m => `
                        <tr>
                            <td>${m.email}</td>
                            <td>
                                <span class="role-badge role-${m.role}">成员</span>
                            </td>
                            <td>${formatDateTime(m.added_at)}</td>
                            <td style="text-align: right;">
                                <button onclick="revokeInvite('${teamId}', '${m.email}', true)" class="btn btn-sm btn-warning">
                                    <i data-lucide="undo"></i> 撤回
                                </button>
                            </td>
                        </tr>
                    `).join('');
                }
            }

            if (window.lucide) lucide.createIcons();
        } else {
            const errorMsg = `<tr><td colspan="4" style="text-align: center; color: var(--danger);">${result.error}</td></tr>`;
            if (joinedTableBody) joinedTableBody.innerHTML = errorMsg;
            if (invitedTableBody) invitedTableBody.innerHTML = errorMsg;
        }
    } catch (error) {
        const errorMsg = '<tr><td colspan="4" style="text-align: center; color: var(--danger);">加载失败</td></tr>';
        if (joinedTableBody) joinedTableBody.innerHTML = errorMsg;
        if (invitedTableBody) invitedTableBody.innerHTML = errorMsg;
    }
}

async function revokeInvite(teamId, email, inModal = false) {
    const confirmed = await showSystemConfirm({
        title: '确认撤回邀请',
        message: `确定要撤回对 "${email}" 的邀请吗？`,
        confirmText: '撤回',
        danger: true,
    });
    if (!confirmed) {
        return;
    }

    try {
        showToast('正在撤回...', 'info');
        const result = await apiCall(`/admin/teams/${teamId}/invites/revoke`, {
            method: 'POST',
            body: JSON.stringify({ email: email })
        });

        if (result.success) {
            showToast('撤回成功', 'success');
            if (inModal) {
                await loadModalMemberList(teamId);
            } else {
                setTimeout(() => location.reload(), 1000);
            }
        } else {
            showToast(result.error || '撤回失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    }
}

async function handleAddMember(event) {
    event.preventDefault();
    const form = event.target;
    const email = form.email.value.trim();
    const submitButton = document.getElementById('addMemberSubmitBtn');
    const teamId = window.currentTeamId;

    if (!teamId) {
        showToast('无法获取 Team ID', 'error');
        return;
    }

    submitButton.disabled = true;
    const originalText = submitButton.innerHTML;
    submitButton.textContent = '添加中...';

    try {
        const result = await apiCall(`/admin/teams/${teamId}/members/add`, {
            method: 'POST',
            body: JSON.stringify({ email })
        });

        if (result.success) {
            showToast('成员添加成功！', 'success');
            form.reset();
            if (document.getElementById('manageMembersModal').classList.contains('show')) {
                await loadModalMemberList(teamId);
            }
            refreshAdminListView(1500, ['manageMembersModal']);
        } else {
            showToast(result.error || '添加失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    }
}

async function deleteMember(teamId, userId, email, inModal = false) {
    const confirmed = await showSystemConfirm({
        title: '确认删除成员',
        message: `确定要删除成员 "${email}" 吗？\n\n此操作不可恢复！`,
        confirmText: '删除',
        danger: true,
    });
    if (!confirmed) {
        return;
    }

    try {
        showToast('正在删除...', 'info');
        const result = await apiCall(`/admin/teams/${teamId}/members/${userId}/delete`, {
            method: 'POST'
        });

        if (result.success) {
            showToast('删除成功', 'success');
            if (inModal) {
                await loadModalMemberList(teamId);
            } else {
                setTimeout(() => location.reload(), 1000);
            }
        } else {
            showToast(result.error || '删除失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    }
}
