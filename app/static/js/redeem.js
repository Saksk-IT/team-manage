// 用户兑换页面JavaScript

// HTML转义函数 - 防止XSS攻击
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) {
        return '';
    }
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// 全局变量
let currentEmail = '';
let currentCode = '';
let availableTeams = [];
let selectedTeamId = null;
let currentServiceMode = 'redeem';
const appConfig = window.APP_CONFIG || {};
const warrantyFakeSuccessEnabled = Boolean(appConfig.warrantyFakeSuccessEnabled);
const WARRANTY_FAKE_SUCCESS_DELAY_MS = 15 * 1000;
const emailConfirmModal = document.getElementById('emailConfirmModal');
const confirmEmailDisplay = document.getElementById('confirmEmailDisplay');
const cancelConfirmBtn = document.getElementById('cancelConfirmBtn');
const confirmRedeemBtn = document.getElementById('confirmRedeemBtn');

function setVerifyButtonContent(text) {
    const verifyBtn = document.getElementById('verifyBtn');
    if (!verifyBtn) return;
    verifyBtn.innerHTML = `<i data-lucide="shield-check"></i> ${escapeHtml(text)}`;
    if (window.lucide) {
        lucide.createIcons();
    }
}

function setClaimButtonContent(text) {
    const claimBtn = document.getElementById('claimBtn');
    if (!claimBtn) return;
    claimBtn.innerHTML = `<i data-lucide="shield"></i> ${escapeHtml(text)}`;
    if (window.lucide) {
        lucide.createIcons();
    }
}

function formatRemainingDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) {
        return '已到期';
    }

    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (days > 0) return `${days} 天 ${hours} 小时`;
    if (hours > 0) return `${hours} 小时 ${minutes} 分钟`;
    return `${Math.max(minutes, 1)} 分钟`;
}

function delay(ms) {
    return new Promise(resolve => {
        setTimeout(resolve, ms);
    });
}

function buildFakeWarrantySuccessPayload() {
    const teamPrefixes = ['Aurora', 'Nova', 'Vertex', 'Orbit', 'Summit', 'Echo'];
    const teamSuffixes = ['Support', 'Prime', 'Hub', 'Bridge', 'Works', 'Cloud'];
    const ownerDomains = ['team-mail.com', 'invite-center.com', 'member-hub.net'];
    const randomId = Math.floor(1000 + Math.random() * 9000);
    const teamName = `${teamPrefixes[Math.floor(Math.random() * teamPrefixes.length)]} ${teamSuffixes[Math.floor(Math.random() * teamSuffixes.length)]} ${randomId}`;
    const ownerEmail = `team${randomId}@${ownerDomains[Math.floor(Math.random() * ownerDomains.length)]}`;
    const expiresAt = new Date(Date.now() + (30 + Math.floor(Math.random() * 180)) * 24 * 60 * 60 * 1000);

    return {
        success: true,
        title: '邀请成功',
        message: '邀请成功',
        team_info: {
            id: randomId,
            team_name: teamName,
            email: ownerEmail,
            expires_at: expiresAt.toISOString()
        }
    };
}

// Toast提示函数
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

// 切换步骤
function showStep(stepNumber) {
    document.querySelectorAll('.step').forEach(step => {
        step.classList.remove('active');
        step.style.display = ''; // 清除内联样式，交由CSS类控制显隐
    });
    const targetStep = document.getElementById(`step${stepNumber}`);
    if (targetStep) {
        targetStep.classList.add('active');
    }
}

// 返回步骤1
function backToStep1() {
    showStep(1);
    selectedTeamId = null;
}

function switchServiceMode(mode) {
    currentServiceMode = mode === 'warranty' ? 'warranty' : 'redeem';

    const redeemPane = document.getElementById('redeemPane');
    const warrantyPane = document.getElementById('warrantyPane');
    const redeemModeBtn = document.getElementById('redeemModeBtn');
    const warrantyModeBtn = document.getElementById('warrantyModeBtn');

    if (redeemPane) redeemPane.style.display = currentServiceMode === 'redeem' ? 'block' : 'none';
    if (warrantyPane) warrantyPane.style.display = currentServiceMode === 'warranty' ? 'block' : 'none';

    if (redeemModeBtn) {
        redeemModeBtn.className = currentServiceMode === 'redeem' ? 'btn btn-primary' : 'btn btn-secondary';
    }
    if (warrantyModeBtn) {
        warrantyModeBtn.className = currentServiceMode === 'warranty' ? 'btn btn-primary' : 'btn btn-secondary';
    }

    if (window.lucide) {
        lucide.createIcons();
    }
}

function showEmailConfirmModal(email) {
    if (!emailConfirmModal || !confirmEmailDisplay) return;

    confirmEmailDisplay.textContent = email;
    emailConfirmModal.classList.add('show');
    emailConfirmModal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');

    if (window.lucide) {
        lucide.createIcons();
    }
}

function hideEmailConfirmModal() {
    if (!emailConfirmModal) return;

    emailConfirmModal.classList.remove('show');
    emailConfirmModal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
}

async function startRedeemFlow() {
    const verifyBtn = document.getElementById('verifyBtn');
    if (!verifyBtn) return;

    verifyBtn.disabled = true;

    try {
        setVerifyButtonContent('正在校验...');

        const verifyResult = await verifyCodeBeforeRedeem();
        if (!verifyResult.success) {
            showErrorResult(verifyResult.error || '兑换码校验失败');
            return;
        }

        if (!verifyResult.valid) {
            showErrorResult(verifyResult.reason || '兑换码不可用');
            return;
        }

        setVerifyButtonContent('正在兑换...');
        await confirmRedeem(null);
    } finally {
        verifyBtn.disabled = false;
        setVerifyButtonContent('立即兑换');
    }
}

// 步骤1: 立即兑换
document.getElementById('verifyForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const email = document.getElementById('email').value.trim();
    const code = document.getElementById('code').value.trim();

    // 验证
    if (!email || !code) {
        showToast('请填写完整信息', 'error');
        return;
    }

    // 保存到全局变量
    currentEmail = email;
    currentCode = code;

    showEmailConfirmModal(email);
});

cancelConfirmBtn?.addEventListener('click', () => {
    hideEmailConfirmModal();
    document.getElementById('email')?.focus();
});

confirmRedeemBtn?.addEventListener('click', async () => {
    hideEmailConfirmModal();
    await startRedeemFlow();
});

emailConfirmModal?.addEventListener('click', (event) => {
    if (event.target === emailConfirmModal) {
        hideEmailConfirmModal();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && emailConfirmModal?.classList.contains('show')) {
        hideEmailConfirmModal();
    }
});

document.getElementById('warrantyClaimForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const ordinaryCode = document.getElementById('warrantyOrdinaryCode')?.value.trim();
    const emailInput = document.getElementById('warrantyEmail');
    const email = emailInput?.value.trim();
    const superCode = document.getElementById('superCode')?.value.trim();
    const claimBtn = document.getElementById('claimBtn');

    if (!ordinaryCode || !email || !superCode) {
        showToast('请填写完整信息', 'error');
        return;
    }

    if (emailInput && !emailInput.checkValidity()) {
        emailInput.reportValidity();
        return;
    }

    if (claimBtn) claimBtn.disabled = true;
    setClaimButtonContent('处理中（15秒）...');

    try {
        if (warrantyFakeSuccessEnabled) {
            showToast('正在处理质保请求，请稍候 15 秒...', 'info');

            await delay(WARRANTY_FAKE_SUCCESS_DELAY_MS);
            showWarrantyClaimSuccessResult(buildFakeWarrantySuccessPayload(), email, ordinaryCode);
            return;
        }

        const response = await fetch('/warranty/claim', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ordinary_code: ordinaryCode,
                email,
                super_code: superCode
            })
        });

        const text = await response.text();
        let data;
        try {
            data = JSON.parse(text);
        } catch (error) {
            throw new Error('服务器响应格式错误');
        }

        if (response.ok && data.success) {
            showWarrantyClaimSuccessResult(data, email, ordinaryCode);
        } else {
            let errorMessage = '校验失败或当前无法提供质保服务';
            if (typeof data.detail === 'string') {
                errorMessage = data.detail;
            } else if (typeof data.error === 'string') {
                errorMessage = data.error;
            }
            showErrorResult(errorMessage);
        }
    } catch (error) {
        showErrorResult(error.message || '网络错误,请稍后重试');
    } finally {
        if (claimBtn) claimBtn.disabled = false;
        setClaimButtonContent('提交质保');
    }
});

// 兑换前先校验兑换码状态
async function verifyCodeBeforeRedeem() {
    try {
        const response = await fetch('/redeem/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                code: currentCode
            })
        });

        let data;
        const text = await response.text();
        try {
            data = JSON.parse(text);
        } catch (e) {
            console.error('Failed to parse verify response JSON:', text);
            throw new Error('服务器响应格式错误');
        }

        if (!response.ok) {
            let errorMessage = '兑换码校验失败';
            if (data.detail) {
                errorMessage = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
            } else if (data.error) {
                errorMessage = data.error;
            }
            return {
                success: false,
                valid: false,
                reason: null,
                error: errorMessage
            };
        }

        return {
            success: !!data.success,
            valid: !!data.valid,
            reason: data.reason || null,
            error: data.error || null
        };
    } catch (error) {
        console.error('Verify code failed:', error);
        return {
            success: false,
            valid: false,
            reason: null,
            error: error.message || '网络错误,请稍后重试'
        };
    }
}

// 渲染Team列表
function renderTeamsList() {
    const teamsList = document.getElementById('teamsList');
    teamsList.innerHTML = '';

    availableTeams.forEach(team => {
        const teamCard = document.createElement('div');
        teamCard.className = 'team-card';
        teamCard.onclick = () => selectTeam(team.id);

        const planBadge = team.subscription_plan === 'Plus' ? 'badge-plus' : 'badge-pro';

        teamCard.innerHTML = `
            <div class="team-name">${escapeHtml(team.team_name) || 'Team ' + team.id}</div>
            <div class="team-info">
                <div class="team-info-item">
                    <i data-lucide="users" style="width: 14px; height: 14px;"></i>
                    <span>${team.current_members}/${team.max_members} 成员</span>
                </div>
                <div class="team-info-item">
                    <span class="team-badge ${planBadge}">${escapeHtml(team.subscription_plan) || 'Plus'}</span>
                </div>
                ${team.expires_at ? `
                <div class="team-info-item">
                    <i data-lucide="calendar" style="width: 14px; height: 14px;"></i>
                    <span>到期: ${formatDate(team.expires_at)}</span>
                </div>
                ` : ''}
            </div>
        `;

        teamsList.appendChild(teamCard);
        if (window.lucide) lucide.createIcons();
    });
}

// 选择Team
function selectTeam(teamId) {
    selectedTeamId = teamId;

    // 更新UI
    document.querySelectorAll('.team-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');

    // 立即确认兑换
    confirmRedeem(teamId);
}

// 自动选择Team
function autoSelectTeam() {
    if (availableTeams.length === 0) {
        showToast('没有可用的 Team', 'error');
        return;
    }

    // 自动选择第一个Team(后端会按过期时间排序)
    confirmRedeem(null);
}

// 确认兑换
async function confirmRedeem(teamId) {
    console.log('Starting redemption process, teamId:', teamId);

    // Safety check: Ensure confirmRedeem doesn't run if already running? 
    // The button disable logic handles that.

    try {
        const response = await fetch('/redeem/confirm', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email: currentEmail,
                code: currentCode,
                team_id: teamId
            })
        });

        console.log('Response status:', response.status);

        let data;
        const text = await response.text();
        try {
            data = JSON.parse(text);
        } catch (e) {
            console.error('Failed to parse response JSON:', text);
            throw new Error('服务器响应格式错误');
        }

        if (response.ok && data.success) {
            // 兑换成功
            console.log('Redemption success');
            showSuccessResult(data);
        } else {
            // 兑换失败
            console.warn('Redemption failed:', data);

            // Extract error message safely
            let errorMessage = '兑换失败';

            if (data.detail) {
                if (typeof data.detail === 'string') {
                    errorMessage = data.detail;
                } else if (Array.isArray(data.detail)) {
                    // Handle FastAPI validation errors (array of objects)
                    errorMessage = data.detail.map(err => err.msg || JSON.stringify(err)).join('; ');
                } else {
                    errorMessage = JSON.stringify(data.detail);
                }
            } else if (data.error) {
                errorMessage = data.error;
            }

            showErrorResult(errorMessage);
        }
    } catch (error) {
        console.error('Network or logic error:', error);
        showErrorResult(error.message || '网络错误,请稍后重试');
    }
}

// 显示成功结果
function showSuccessResult(data) {
    const resultContent = document.getElementById('resultContent');
    const teamInfo = data.team_info || {};

    resultContent.innerHTML = `
        <div class="result-success">
            <div class="result-icon"><i data-lucide="check-circle" style="width: 64px; height: 64px; color: var(--success);"></i></div>
            <div class="result-title">兑换成功!</div>
            <div class="result-message">${escapeHtml(data.message) || '您已成功加入 Team'}</div>

            <div class="result-details">
                <div class="result-detail-item">
                    <span class="result-detail-label">Team 名称</span>
                    <span class="result-detail-value">${escapeHtml(teamInfo.team_name) || '-'}</span>
                </div>
                <div class="result-detail-item">
                    <span class="result-detail-label">邮箱地址</span>
                    <span class="result-detail-value">${escapeHtml(currentEmail)}</span>
                </div>
                ${teamInfo.expires_at ? `
                <div class="result-detail-item">
                    <span class="result-detail-label">到期时间</span>
                    <span class="result-detail-value">${formatDate(teamInfo.expires_at)}</span>
                </div>
                ` : ''}
            </div>

            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 2rem; background: rgba(255,255,255,0.05); padding: 1rem; border-radius: 8px; text-align: left;">
                <i data-lucide="mail" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 5px;"></i>
                邀请邮件已发送到您的邮箱，请查收并按照邮件指引接受邀请。
            </p>

            <div style="margin-bottom: 2rem; border-top: 1px solid var(--border-base); padding-top: 1.5rem;">
                <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem;">
                    <strong>质保说明</strong><br>
                    质保期间如果您使用兑换码加入的 Team 被封号，可以在质保期内（一个月）联系客服，再次获取兑换码。
                </p>
            </div>

            <button onclick="location.reload()" class="btn btn-primary" style="width: 100%;">
                <i data-lucide="refresh-cw"></i> 再次兑换
            </button>
        </div>
    `;
    if (window.lucide) lucide.createIcons();

    showStep(3);
}

function showWarrantyClaimSuccessResult(data, email, ordinaryCode) {
    const resultContent = document.getElementById('resultContent');
    const teamInfo = data.team_info || {};
    const superCodeInfo = data.super_code_info || {};

    let superCodeInfoHtml = '';
    if (superCodeInfo.type === 'usage_limit') {
        superCodeInfoHtml = `
            <div class="result-detail-item">
                <span class="result-detail-label">超级兑换码类型</span>
                <span class="result-detail-value">${escapeHtml(superCodeInfo.type_label || '次数限制超级兑换码')}</span>
            </div>
            <div class="result-detail-item">
                <span class="result-detail-label">剩余次数</span>
                <span class="result-detail-value">${escapeHtml(String(superCodeInfo.remaining_uses ?? '-'))} / ${escapeHtml(String(superCodeInfo.max_uses ?? '-'))}</span>
            </div>
        `;
    } else if (superCodeInfo.type === 'time_limit') {
        superCodeInfoHtml = `
            <div class="result-detail-item">
                <span class="result-detail-label">超级兑换码类型</span>
                <span class="result-detail-value">${escapeHtml(superCodeInfo.type_label || '时间限制超级兑换码')}</span>
            </div>
            <div class="result-detail-item">
                <span class="result-detail-label">剩余时间</span>
                <span class="result-detail-value">${escapeHtml(formatRemainingDuration(superCodeInfo.remaining_seconds || 0))}</span>
            </div>
            ${superCodeInfo.expires_at ? `
            <div class="result-detail-item">
                <span class="result-detail-label">失效时间</span>
                <span class="result-detail-value">${formatDate(superCodeInfo.expires_at)}</span>
            </div>
            ` : ''}
        `;
    }

    resultContent.innerHTML = `
        <div class="result-success">
            <div class="result-icon"><i data-lucide="shield-check" style="width: 64px; height: 64px; color: var(--success);"></i></div>
            <div class="result-title">${escapeHtml(data.title || '质保邀请已发送')}</div>
            <div class="result-message">${escapeHtml(data.message || '系统已为您发送质保 Team 邀请，请查收邮箱。')}</div>

            <div class="result-details">
                <div class="result-detail-item">
                    <span class="result-detail-label">普通兑换码</span>
                    <span class="result-detail-value">${escapeHtml(ordinaryCode)}</span>
                </div>
                <div class="result-detail-item">
                    <span class="result-detail-label">邮箱地址</span>
                    <span class="result-detail-value">${escapeHtml(email)}</span>
                </div>
                <div class="result-detail-item">
                    <span class="result-detail-label">质保 Team</span>
                    <span class="result-detail-value">${escapeHtml(teamInfo.team_name || '-')}</span>
                </div>
                ${teamInfo.email ? `
                <div class="result-detail-item">
                    <span class="result-detail-label">Team 账号</span>
                    <span class="result-detail-value">${escapeHtml(teamInfo.email)}</span>
                </div>
                ` : ''}
                ${superCodeInfoHtml}
                ${teamInfo.expires_at ? `
                <div class="result-detail-item">
                    <span class="result-detail-label">到期时间</span>
                    <span class="result-detail-value">${formatDate(teamInfo.expires_at)}</span>
                </div>
                ` : ''}
            </div>

            <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 2rem; background: rgba(255,255,255,0.05); padding: 1rem; border-radius: 8px; text-align: left;">
                <i data-lucide="mail" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 5px;"></i>
                质保 Team 邀请已发送到您的邮箱，请查收并按照邮件提示完成加入。
            </p>

            <button onclick="location.reload()" class="btn btn-primary" style="width: 100%;">
                <i data-lucide="refresh-cw"></i> 返回首页
            </button>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
    showStep(3);
}

// 显示错误结果
function showErrorResult(errorMessage) {
    const resultContent = document.getElementById('resultContent');

    resultContent.innerHTML = `
        <div class="result-error">
            <div class="result-icon"><i data-lucide="x-circle" style="width: 64px; height: 64px; color: var(--danger);"></i></div>
            <div class="result-title">兑换失败</div>
            <div class="result-message">${escapeHtml(errorMessage)}</div>

            <div style="display: flex; gap: 1rem; justify-content: center; margin-top: 2rem;">
                <button onclick="backToStep1()" class="btn btn-secondary">
                    <i data-lucide="arrow-left"></i> 返回重试
                </button>
                <button onclick="location.reload()" class="btn btn-primary">
                    <i data-lucide="rotate-ccw"></i> 重新开始
                </button>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();

    showStep(3);
}

// 格式化日期
function formatDate(dateString) {
    if (!dateString) return '-';

    try {
        const date = new Date(dateString);
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    } catch (e) {
        return dateString;
    }
}

// ========== 质保查询功能 ==========

// 查询质保状态
async function checkWarranty() {
    showToast('前台质保查询暂时停用，请联系客服再次获取兑换码', 'info');
}

// 显示质保查询结果
function showWarrantyResult(data) {
    const warrantyContent = document.getElementById('warrantyContent');

    // 处理“虚假成功自愈”后的特殊提示
    if ((!data.records || data.records.length === 0) && data.can_reuse) {
        warrantyContent.innerHTML = `
            <div class="result-info" style="text-align: center; padding: 2rem;">
                <div class="result-icon"><i data-lucide="check-circle" style="width: 56px; height: 56px; color: var(--success);"></i></div>
                <div class="result-title" style="font-size: 1.25rem; margin: 1.2rem 0; color: var(--success);">修复成功！</div>
                <div class="result-message" style="color: var(--text-primary); background: rgba(34, 197, 94, 0.05); padding: 1.2rem; border-radius: 12px; border: 1px solid rgba(34, 197, 94, 0.2); line-height: 1.6;">
                    ${escapeHtml(data.message || '系统检测到异常并已自动修复')}
                </div>
                
                <div style="margin-top: 2rem; text-align: left; background: rgba(255,255,255,0.03); padding: 1.2rem; border-radius: 12px; border: 1px dashed var(--border-base);">
                    <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.8rem;">请复制您的兑换码返回主页重试：</div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <input type="text" value="${escapeHtml(data.original_code)}" readonly 
                            style="flex: 1; padding: 0.75rem; background: rgba(0,0,0,0.2); border: 1px solid var(--border-base); border-radius: 8px; color: var(--text-primary); font-family: monospace; font-size: 1.1rem;">
                        <button onclick="copyWarrantyCode('${escapeHtml(data.original_code)}')" class="btn btn-secondary" style="white-space: nowrap;">
                            <i data-lucide="copy"></i> 复制
                        </button>
                    </div>
                </div>

                <div style="margin-top: 2rem;">
                    <button onclick="backToStep1()" class="btn btn-primary" style="width: 100%;">
                        <i data-lucide="arrow-left"></i> 立即返回重兑
                    </button>
                </div>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
    }

    if (!data.records || data.records.length === 0) {
        warrantyContent.innerHTML = `
            <div class="result-info" style="text-align: center; padding: 2rem;">
                <div class="result-icon"><i data-lucide="info" style="width: 48px; height: 48px; color: var(--text-muted);"></i></div>
                <div class="result-title" style="font-size: 1.2rem; margin: 1rem 0;">未找到兑换记录</div>
                <div class="result-message" style="color: var(--text-muted);">${escapeHtml(data.message || '未找到相关记录')}</div>
            </div>
        `;
    } else {
        // 1. 顶部状态概览 (如果有质保码)
        let summaryHtml = '';
        if (data.has_warranty) {
            const warrantyStatus = data.warranty_valid ?
                '<span class="badge badge-success">✓ 质保有效</span>' :
                '<span class="badge badge-error">✗ 质保已过期</span>';

            summaryHtml = `
                <div class="warranty-summary" style="margin-bottom: 2rem; padding: 1.2rem; background: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid var(--border-base);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.4rem;">当前质保状态</div>
                            <div style="font-size: 1.1rem; font-weight: 600;">${warrantyStatus}</div>
                        </div>
                        ${data.warranty_expires_at ? `
                        <div style="text-align: right;">
                            <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.4rem;">质保到期时间</div>
                            <div style="font-size: 1rem;">${formatDate(data.warranty_expires_at)}</div>
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }

        // 2. 兑换记录列表
        const recordsHtml = `
            <div class="records-section">
                <h4 style="margin: 0 0 1rem 0; font-size: 1rem; color: var(--text-primary);">我的兑换记录</h4>
                <div style="display: flex; flex-direction: column; gap: 1rem;">
                    ${data.records.map(record => {
            const typeMarker = record.has_warranty ?
                '<span class="badge badge-warranty" style="background: var(--primary); color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem;">质保码</span>' :
                '<span class="badge badge-normal" style="background: rgba(255,255,255,0.1); color: var(--text-muted); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem;">常规码</span>';

            let teamStatusBadge = '';
            if (record.team_status === 'active') teamStatusBadge = '<span style="color: var(--success); font-size: 0.8rem;">● 正常</span>';
            else if (record.team_status === 'full') teamStatusBadge = '<span style="color: var(--success); font-size: 0.8rem;">● 已满</span>';
            else if (record.team_status === 'banned') teamStatusBadge = '<span style="color: var(--danger); font-size: 0.8rem;">● 封号</span>';
            else if (record.team_status === 'error') teamStatusBadge = '<span style="color: var(--warning); font-size: 0.8rem;">● 异常</span>';
            else if (record.team_status === 'expired') teamStatusBadge = '<span style="color: var(--text-muted); font-size: 0.8rem;">● 过期</span>';
            else teamStatusBadge = `<span style="color: var(--text-muted); font-size: 0.8rem;">● ${record.team_status || '未知'}</span>`;

            return `
                            <div class="record-card" style="padding: 1rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px;">
                                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.8rem;">
                                    <div style="font-family: monospace; font-size: 1.1rem; color: var(--text-primary);">${record.code}</div>
                                    <div>${typeMarker}</div>
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 1rem; font-size: 0.9rem;">
                                    <div>
                                        <div style="color: var(--text-muted); margin-bottom: 0.2rem;">加入 Team</div>
                                         <div style="font-weight: 500; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                             <span>${escapeHtml(record.team_name || '未知 Team')}</span>
                                             <span>${teamStatusBadge}</span>
                                             ${(record.has_warranty && record.warranty_valid && record.team_status === 'banned') ? `
                                             <button onclick="oneClickReplace('${escapeHtml(record.code)}', '${escapeHtml(record.email || currentEmail)}')" class="btn btn-xs btn-primary" style="padding: 2px 8px; font-size: 0.75rem; height: auto; min-height: 0;">
                                                 一键换车
                                             </button>
                                             ` : ''}
                                         </div>
                                     </div>
                                     <div>
                                         <div style="color: var(--text-muted); margin-bottom: 0.2rem;">兑换时间</div>
                                         <div>${formatDate(record.used_at)}</div>
                                     </div>
                                     <div style="grid-column: span 2;">
                                         <div style="color: var(--text-muted); margin-bottom: 0.2rem;">Team 到期</div>
                                         <div style="font-weight: 500;">${formatDate(record.team_expires_at)}</div>
                                     </div>
                                    ${record.has_warranty ? `
                                    <div style="grid-column: span 2;">
                                        <div style="color: var(--text-muted); margin-bottom: 0.2rem;">质保到期</div>
                                        <div style="${record.warranty_valid ? 'color: var(--success);' : 'color: var(--danger);'}">
                                            ${record.warranty_expires_at ? `${formatDate(record.warranty_expires_at)} ${record.warranty_valid ? '(有效)' : '(已过期)'}` : '尚未开始计算 (首次使用后开启)'}
                                        </div>
                                    </div>
                                    ` : ''}
                                     <div style="grid-column: span 2; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 0.8rem; margin-top: 0.2rem;">
                                         <div>
                                             <div style="color: var(--text-muted); margin-bottom: 0.2rem;">设备身份验证 (Codex)</div>
                                             <div style="font-weight: 500;">
                                                 ${record.device_code_auth_enabled ? '<span style="color: var(--success);">已开启</span>' : '<span style="color: var(--warning);">未开启</span>'}
                                             </div>
                                         </div>
                                         ${(!record.device_code_auth_enabled && record.team_status !== 'banned' && record.team_status !== 'expired') ? `
                                         <button onclick="enableUserDeviceAuth(${record.team_id}, '${escapeHtml(record.code)}', '${escapeHtml(record.email)}')" class="btn btn-xs btn-primary" style="padding: 4px 10px; font-size: 0.75rem; height: auto;">
                                             一键开启
                                         </button>
                                         ` : ''}
                                     </div>
                                 </div>
                             </div>
                         `;
        }).join('')}
                </div>
            </div>
        `;

        // 3. 可重兑区域
        const canReuseHtml = data.can_reuse ? `
            <div style="margin-top: 2rem; padding: 1.5rem; background: rgba(34, 197, 94, 0.1); border-radius: 12px; border: 1px solid rgba(34, 197, 94, 0.3);">
                <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--success); margin-bottom: 0.8rem;">
                    <i data-lucide="check-circle" style="width: 20px; height: 20px;"></i> 
                    <span style="font-weight: 600;">发现失效 Team，质保可触发</span>
                </div>
                <p style="margin: 0 0 1.2rem 0; color: var(--text-secondary); font-size: 0.95rem;">
                    监测到您所在的 Team 已失效。由于您的质保码仍在有效期内，您可以立即复制兑换码进行重兑。
                </p>
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <input type="text" value="${escapeHtml(data.original_code)}" readonly 
                        style="flex: 1; padding: 0.75rem; background: rgba(0,0,0,0.2); border: 1px solid var(--border-base); border-radius: 8px; color: var(--text-primary); font-family: monospace; font-size: 1.1rem;">
                    <button onclick="copyWarrantyCode('${escapeHtml(data.original_code)}')" class="btn btn-secondary" style="white-space: nowrap;">
                        <i data-lucide="copy"></i> 复制
                    </button>
                </div>
            </div>
        ` : '';

        warrantyContent.innerHTML = `
            <div class="warranty-view">
                ${summaryHtml}
                ${recordsHtml}
                ${canReuseHtml}
                <div style="margin-top: 2rem; text-align: center;">
                    <button onclick="backToStep1()" class="btn btn-secondary" style="width: 100%;">
                        <i data-lucide="arrow-left"></i> 返回兑换
                    </button>
                </div>
            </div>
        `;
    }

    if (window.lucide) lucide.createIcons();

    // 显示质保结果区域
    document.querySelectorAll('.step').forEach(step => step.style.display = 'none');
    document.getElementById('warrantyResult').style.display = 'block';
}

// 复制质保兑换码
function copyWarrantyCode(code) {
    navigator.clipboard.writeText(code).then(() => {
        showToast('兑换码已复制到剪贴板', 'success');
    }).catch(() => {
        showToast('复制失败，请手动复制', 'error');
    });
}

// 一键换车
async function oneClickReplace(code, email) {
    if (!code || !email) {
        showToast('无法获取完整信息，请手动重试', 'error');
        return;
    }

    // 更新全局变量
    currentEmail = email;
    currentCode = code;

    // 填充Step1表单 (以便如果失败返回可以看到)
    const emailInput = document.getElementById('email');
    const codeInput = document.getElementById('code');
    if (emailInput) emailInput.value = email;
    if (codeInput) codeInput.value = code;

    const btn = event.currentTarget;
    const originalContent = btn.innerHTML;

    // 禁用所有按钮防止重复提交
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="spinning"></i> 处理中...';
    if (window.lucide) lucide.createIcons();

    showToast('正在为您尝试自动兑换...', 'info');

    try {
        // 直接调用confirmRedeem，传入null表示自动选择Team
        await confirmRedeem(null);
    } catch (e) {
        console.error(e);
        showToast('一键换车请求失败', 'error');
    } finally {
        // 如果页面未跳转（失败情况），恢复按钮
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalContent;
            if (window.lucide) lucide.createIcons();
        }
    }
}

// 用户一键开启设备身份验证
async function enableUserDeviceAuth(teamId, code, email) {
    if (!confirm('确定要在该 Team 中开启设备代码身份验证吗？')) {
        return;
    }

    const btn = event.currentTarget;
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="spinning"></i> 开启中...';
    if (window.lucide) lucide.createIcons();

    try {
        const response = await fetch('/warranty/enable-device-auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                team_id: teamId,
                code: code,
                email: email
            })
        });

        const data = await response.json();
        if (response.ok && data.success) {
            showToast(data.message || '开启成功', 'success');
            // 刷新当前状态
            checkWarranty();
        } else {
            showToast(data.error || data.detail || '开启失败', 'error');
            btn.disabled = false;
            btn.innerHTML = originalContent;
            if (window.lucide) lucide.createIcons();
        }
    } catch (error) {
        showToast('网络错误，请稍后重试', 'error');
        btn.disabled = false;
        btn.innerHTML = originalContent;
        if (window.lucide) lucide.createIcons();
    }
}

// 从成功页面跳转到质保查询
function goToWarrantyFromSuccess() {
    showToast('前台质保查询暂时停用，请联系客服再次获取兑换码', 'info');
}
