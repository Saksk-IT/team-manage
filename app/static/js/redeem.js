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
let currentWarrantyEmail = '';
let currentWarrantyStatus = null;
const appConfig = window.APP_CONFIG || {};
const redeemServiceEnabled = appConfig.redeemServiceEnabled !== false;
const warrantyServiceEnabled = Boolean(appConfig.warrantyServiceEnabled);
const warrantyEmailCheckEnabled = warrantyServiceEnabled && Boolean(appConfig.warrantyEmailCheckEnabled);
const warrantyFakeSuccessEnabled = warrantyServiceEnabled && !warrantyEmailCheckEnabled && Boolean(appConfig.warrantyFakeSuccessEnabled);
let currentServiceMode = redeemServiceEnabled ? 'redeem' : (warrantyServiceEnabled ? 'warranty' : 'redeem');
const WARRANTY_FAKE_SUCCESS_DELAY_MS = 15 * 1000;
const WARRANTY_FAKE_SUCCESS_MIN_SPOTS = 60;
const WARRANTY_FAKE_SUCCESS_MAX_SPOTS = 100;
let currentDisplayedRemainingSpots = Number(appConfig.initialRemainingSpots);
const emailConfirmModal = document.getElementById('emailConfirmModal');
const confirmEmailDisplay = document.getElementById('confirmEmailDisplay');
const cancelConfirmBtn = document.getElementById('cancelConfirmBtn');
const confirmRedeemBtn = document.getElementById('confirmRedeemBtn');
const customerServiceWidget = document.getElementById('customerServiceWidget');
const customerServiceFab = document.getElementById('customerServiceFab');
const customerServicePanel = document.getElementById('customerServicePanel');
const customerServiceCloseBtn = document.getElementById('customerServiceCloseBtn');
const customerServicePromptModal = document.getElementById('customerServicePromptModal');
const customerServicePromptCloseBtn = document.getElementById('customerServicePromptCloseBtn');
const customerServicePromptConfirmBtn = document.getElementById('customerServicePromptConfirmBtn');
const requestTransitionOverlay = document.getElementById('requestTransitionOverlay');
const transitionOverlayIcon = document.getElementById('transitionOverlayIcon');
const transitionOverlayEyebrow = document.getElementById('transitionOverlayEyebrow');
const transitionOverlayTitle = document.getElementById('transitionOverlayTitle');
const transitionOverlayMessage = document.getElementById('transitionOverlayMessage');
const transitionOverlayTimeline = document.getElementById('transitionOverlayTimeline');
const transitionOverlayHint = document.getElementById('transitionOverlayHint');
let transitionOverlayState = {
    flow: null,
    stageIndex: 0,
    startedAt: 0
};
let transitionOverlayStageTimerId = null;
let transitionOverlayHintTimerId = null;
let transitionOverlayCountdownTimerId = null;

const REDEEM_LOADING_FLOW = Object.freeze({
    icon: 'ticket',
    eyebrow: '兑换服务',
    title: '正在为您加入 Team',
    message: '请稍候，我们正在自动完成兑换。',
    stages: Object.freeze([
        Object.freeze({
            label: '核对兑换资格',
            message: '正在验证兑换码状态与邮箱信息，请稍候。'
        }),
        Object.freeze({
            label: '锁定可用席位',
            message: '资格校验通过后，会自动为您匹配可用席位。'
        }),
        Object.freeze({
            label: '发送 Team 邀请',
            message: '席位锁定完成后，系统会把邀请发到您的邮箱。'
        })
    ]),
    hints: Object.freeze([
        '结果出来后会自动展示，无需反复刷新页面。',
        '处理中请勿重复提交，以免生成重复请求。',
        '如果网络稍慢，请保持当前页面开启，我们会继续处理。'
    ]),
    autoStageDelayMs: 2200
});

const WARRANTY_STATUS_LOADING_FLOW = Object.freeze({
    icon: 'search',
    eyebrow: '质保订单查询',
    title: '正在查询质保订单',
    message: '系统正在按邮箱读取质保订单与剩余额度。',
    stages: Object.freeze([
        Object.freeze({
            label: '核对质保邮箱',
            message: '正在验证质保邮箱与兑换码是否匹配。'
        }),
        Object.freeze({
            label: '查询订单列表',
            message: '正在读取该邮箱对应的质保订单。'
        }),
        Object.freeze({
            label: '整理剩余额度',
            message: '正在整理兑换码、剩余次数和剩余时间。'
        })
    ]),
    hints: Object.freeze([
        '查询订单不会自动判断 Team 状态，需要在订单卡片中单独刷新。',
        '完成后会自动展示结果，无需重复点击。',
        '请保持页面开启，避免中途中断查询流程。'
    ]),
    autoStageDelayMs: 1800
});

const WARRANTY_ORDER_REFRESH_LOADING_FLOW = Object.freeze({
    icon: 'refresh-cw',
    eyebrow: '订单 Team 刷新',
    title: '正在刷新订单 Team 状态',
    message: '系统会针对该订单对应的 Team 执行一次实时刷新。',
    stages: Object.freeze([
        Object.freeze({
            label: '锁定质保订单',
            message: '正在核对该订单的剩余次数和剩余时间。'
        }),
        Object.freeze({
            label: '执行 Team 刷新',
            message: '正在刷新该订单对应邮箱上次加入的 Team。'
        }),
        Object.freeze({
            label: '返回实时状态',
            message: '正在整理最新 Team 状态和提交权限。'
        })
    ]),
    hints: Object.freeze([
        '只有刷新结果为“封禁”的订单可以提交质保。',
        '如果同一邮箱有多个订单，请分别刷新各订单状态。',
        '刷新过程可能需要几秒，请保持页面开启。'
    ]),
    autoStageDelayMs: 1800
});

const WARRANTY_CLAIM_LOADING_FLOW = Object.freeze({
    icon: 'shield',
    eyebrow: '质保申请',
    title: '正在为您处理质保申请',
    message: '系统会再次复核资格，并为您安排新的质保邀请。',
    stages: Object.freeze([
        Object.freeze({
            label: '复核质保资格',
            message: '正在确认邮箱、质保次数与最近 Team 状态。'
        }),
        Object.freeze({
            label: '匹配可用 Team',
            message: '正在为您查找可用的质保席位。'
        }),
        Object.freeze({
            label: '发送新的邀请',
            message: '资格确认完成后，会自动把新的邀请发到您的邮箱。'
        })
    ]),
    hints: Object.freeze([
        '您无需离开当前页面，完成后会自动显示结果。',
        '请勿重复点击提交，系统只会保留当前这次申请。',
        '如果稍有等待，通常是系统正在匹配可用质保席位。'
    ]),
    countdownHintPrefix: '我们已记录您的申请进度，结果出来后会自动展示。',
    autoStageDelayMs: 2400
});

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
    claimBtn.innerHTML = `<i data-lucide="search"></i> ${escapeHtml(text)}`;
    if (window.lucide) {
        lucide.createIcons();
    }
}

function hasTransitionOverlaySupport() {
    return Boolean(
        requestTransitionOverlay &&
        transitionOverlayIcon &&
        transitionOverlayEyebrow &&
        transitionOverlayTitle &&
        transitionOverlayMessage &&
        transitionOverlayTimeline &&
        transitionOverlayHint
    );
}

function clearTransitionOverlayTimers() {
    if (transitionOverlayStageTimerId) {
        window.clearInterval(transitionOverlayStageTimerId);
        transitionOverlayStageTimerId = null;
    }

    if (transitionOverlayHintTimerId) {
        window.clearInterval(transitionOverlayHintTimerId);
        transitionOverlayHintTimerId = null;
    }

    if (transitionOverlayCountdownTimerId) {
        window.clearInterval(transitionOverlayCountdownTimerId);
        transitionOverlayCountdownTimerId = null;
    }
}

function setTransitionOverlayHint(text) {
    if (!transitionOverlayHint) return;
    transitionOverlayHint.textContent = text || '处理中期间请勿关闭页面或重复提交。';
}

function renderTransitionOverlayIcon(iconName) {
    if (!transitionOverlayIcon) return;

    transitionOverlayIcon.innerHTML = `<i data-lucide="${iconName}"></i>`;
}

function renderTransitionOverlayTimeline(flow, activeStageIndex) {
    if (!transitionOverlayTimeline) return;

    const stages = Array.isArray(flow?.stages) ? flow.stages : [];
    transitionOverlayTimeline.innerHTML = stages.map((stage, index) => {
        const isComplete = index < activeStageIndex;
        const isActive = index === activeStageIndex;
        const classNames = [
            'transition-stage',
            isComplete ? 'transition-stage--complete' : '',
            isActive ? 'transition-stage--active' : ''
        ].filter(Boolean).join(' ');

        return `
            <div class="${classNames}">
                <div class="transition-stage__dot"></div>
                <div class="transition-stage__body">
                    <div class="transition-stage__title">${escapeHtml(stage.label || '')}</div>
                    <div class="transition-stage__message">${escapeHtml(stage.message || '')}</div>
                </div>
            </div>
        `;
    }).join('');
}

function setTransitionOverlayStage(stageIndex, overrides = {}) {
    const flow = transitionOverlayState.flow;
    if (!flow) return;

    const stages = Array.isArray(flow.stages) ? flow.stages : [];
    const safeIndex = Math.max(0, Math.min(stageIndex, Math.max(stages.length - 1, 0)));
    const currentStage = stages[safeIndex] || {};

    transitionOverlayState = {
        ...transitionOverlayState,
        stageIndex: safeIndex
    };

    if (transitionOverlayEyebrow) {
        transitionOverlayEyebrow.textContent = overrides.eyebrow || flow.eyebrow || '安心处理中';
    }

    if (transitionOverlayTitle) {
        transitionOverlayTitle.textContent = overrides.title || flow.title || '正在处理中';
    }

    if (transitionOverlayMessage) {
        transitionOverlayMessage.textContent = overrides.message || currentStage.message || flow.message || '请稍候，结果出来后会自动展示。';
    }

    renderTransitionOverlayTimeline(flow, safeIndex);

    if (window.lucide) {
        lucide.createIcons();
    }
}

function startTransitionOverlayHintRotation(flow) {
    const hints = Array.isArray(flow?.hints) ? flow.hints : [];
    if (hints.length === 0) {
        setTransitionOverlayHint('处理中期间请保持页面开启，我们会自动继续下一步。');
        return;
    }

    let nextHintIndex = 0;
    setTransitionOverlayHint(hints[nextHintIndex]);

    if (hints.length === 1) {
        return;
    }

    transitionOverlayHintTimerId = window.setInterval(() => {
        nextHintIndex = (nextHintIndex + 1) % hints.length;
        setTransitionOverlayHint(hints[nextHintIndex]);
    }, 2600);
}

function startTransitionOverlayCountdown(totalMs) {
    const startedAt = transitionOverlayState.startedAt;
    const prefix = transitionOverlayState.flow?.countdownHintPrefix || '我们已记录您的进度，结果出来后会自动展示。';

    const updateCountdownHint = () => {
        const elapsedMs = Date.now() - startedAt;
        const remainingMs = Math.max(totalMs - elapsedMs, 0);
        const remainingSeconds = Math.ceil(remainingMs / 1000);

        if (remainingSeconds > 0) {
            setTransitionOverlayHint(`${prefix} 预计还需约 ${remainingSeconds} 秒。`);
            return;
        }

        setTransitionOverlayHint('马上为您展示结果，请再稍候一下。');
    };

    updateCountdownHint();
    transitionOverlayCountdownTimerId = window.setInterval(updateCountdownHint, 1000);
}

function scheduleTransitionOverlayStageProgression(flow) {
    const stages = Array.isArray(flow?.stages) ? flow.stages : [];
    if (stages.length <= 1) {
        return;
    }

    const autoStageDelayMs = Number(flow.autoStageDelayMs) > 0 ? Number(flow.autoStageDelayMs) : 2000;
    transitionOverlayStageTimerId = window.setInterval(() => {
        const currentFlow = transitionOverlayState.flow;
        if (!currentFlow || currentFlow !== flow) {
            clearTransitionOverlayTimers();
            return;
        }

        const nextStageIndex = Math.min(transitionOverlayState.stageIndex + 1, stages.length - 1);
        if (nextStageIndex === transitionOverlayState.stageIndex) {
            window.clearInterval(transitionOverlayStageTimerId);
            transitionOverlayStageTimerId = null;
            return;
        }

        setTransitionOverlayStage(nextStageIndex);
    }, autoStageDelayMs);
}

function isTransitionOverlayOpen() {
    return Boolean(requestTransitionOverlay?.classList.contains('show'));
}

function openTransitionOverlay(flow, options = {}) {
    if (!hasTransitionOverlaySupport() || !flow) {
        return;
    }

    clearTransitionOverlayTimers();

    transitionOverlayState = {
        flow,
        stageIndex: Number.isInteger(options.stageIndex) ? options.stageIndex : 0,
        startedAt: Date.now()
    };

    renderTransitionOverlayIcon(flow.icon || 'sparkles');
    setTransitionOverlayStage(transitionOverlayState.stageIndex, {
        title: options.title,
        message: options.message,
        eyebrow: options.eyebrow
    });

    requestTransitionOverlay.classList.add('show');
    requestTransitionOverlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('transition-open');

    const fixedDelayMs = Number.isFinite(options.fixedDelayMs) ? options.fixedDelayMs : null;
    if (fixedDelayMs && fixedDelayMs > 0) {
        startTransitionOverlayCountdown(fixedDelayMs);
    } else {
        startTransitionOverlayHintRotation(flow);
    }

    scheduleTransitionOverlayStageProgression(flow);

    if (window.lucide) {
        lucide.createIcons();
    }
}

function advanceTransitionOverlay(stageIndex, overrides = {}) {
    if (!hasTransitionOverlaySupport() || !transitionOverlayState.flow) {
        return;
    }

    setTransitionOverlayStage(stageIndex, overrides);
}

function closeTransitionOverlay() {
    if (!hasTransitionOverlaySupport()) {
        return;
    }

    clearTransitionOverlayTimers();
    transitionOverlayState = {
        flow: null,
        stageIndex: 0,
        startedAt: 0
    };

    requestTransitionOverlay.classList.remove('show');
    requestTransitionOverlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('transition-open');
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

function isQueuedInviteJob(data) {
    const status = data?.job_status || data?.status;
    return Boolean(data?.job_id && (data?.queued || status === 'queued' || status === 'processing'));
}

function getInviteJobStatus(data) {
    return data?.job_status || data?.status || '';
}

async function waitForInviteJob(initialData, options = {}) {
    const jobId = initialData?.job_id;
    if (!jobId) {
        return initialData;
    }

    const flowType = options.flowType || 'redeem';
    const maxPolls = Number.isFinite(options.maxPolls) ? options.maxPolls : 240;
    let pollAfterMs = Number(initialData.poll_after_ms || 1500);

    for (let pollIndex = 0; pollIndex < maxPolls; pollIndex += 1) {
        const status = getInviteJobStatus(initialData);
        if (pollIndex === 0 && status === 'queued') {
            setTransitionOverlayStage(1, {
                message: '请求已进入队列，系统会按 Team 席位顺序自动处理。'
            });
        }

        await delay(Math.max(pollAfterMs, 800));

        const response = await fetch(`/invite-jobs/${encodeURIComponent(jobId)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json'
            }
        });
        const text = await response.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch (error) {
            throw new Error('服务器响应格式错误');
        }

        if (!response.ok) {
            throw new Error(data?.detail || data?.error || '查询任务状态失败');
        }

        const jobStatus = getInviteJobStatus(data);
        if (jobStatus === 'success') {
            advanceTransitionOverlay(2, {
                message: flowType === 'warranty'
                    ? '质保邀请已发送，正在展示结果。'
                    : 'Team 邀请已发送，正在展示结果。'
            });
            return data;
        }

        if (jobStatus === 'failed' || data?.success === false) {
            throw new Error(data?.error || data?.message || '处理失败，请稍后重试');
        }

        pollAfterMs = Number(data?.poll_after_ms || pollAfterMs || 1500);
        if (jobStatus === 'processing') {
            advanceTransitionOverlay(2, {
                message: flowType === 'warranty'
                    ? '正在发送质保邀请，请继续保持页面开启。'
                    : '正在发送 Team 邀请，请继续保持页面开启。'
            });
        } else {
            setTransitionOverlayHint('请求已记录并排队中，请勿重复提交。');
        }
    }

    throw new Error('请求仍在处理中，请稍后刷新或联系管理员查询结果。');
}

function setCustomerServiceWidgetOpen(isOpen) {
    if (!customerServiceWidget || !customerServiceFab || !customerServicePanel) {
        return;
    }

    customerServiceWidget.classList.toggle('open', isOpen);
    customerServiceFab.setAttribute('aria-expanded', String(isOpen));
    customerServicePanel.setAttribute('aria-hidden', String(!isOpen));
}

function toggleCustomerServiceWidget(forceOpen) {
    if (!customerServiceWidget) {
        return;
    }

    const nextOpenState = typeof forceOpen === 'boolean'
        ? forceOpen
        : !customerServiceWidget.classList.contains('open');

    setCustomerServiceWidgetOpen(nextOpenState);
}

function syncBodyModalState() {
    const hasOpenModal = Boolean(
        emailConfirmModal?.classList.contains('show') ||
        customerServicePromptModal?.classList.contains('show')
    );

    document.body.classList.toggle('modal-open', hasOpenModal);
}

function setCustomerServicePromptOpen(isOpen) {
    if (!customerServicePromptModal) {
        return;
    }

    customerServicePromptModal.classList.toggle('show', isOpen);
    customerServicePromptModal.setAttribute('aria-hidden', String(!isOpen));
    syncBodyModalState();

    if (isOpen && window.lucide) {
        lucide.createIcons();
    }
}

function showCustomerServiceQrReminder() {
    if (!customerServicePromptModal) {
        return;
    }

    const qrImage = customerServicePromptModal.querySelector('.customer-service-modal-qr');
    if (!qrImage) {
        return;
    }

    setCustomerServicePromptOpen(true);
}

function normalizeWarrantyFakeSuccessSpots(value) {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) {
        return null;
    }
    return Math.min(
        WARRANTY_FAKE_SUCCESS_MAX_SPOTS,
        Math.max(WARRANTY_FAKE_SUCCESS_MIN_SPOTS, Math.round(numericValue))
    );
}

function updateRemainingSpotsDisplay(value) {
    const normalizedValue = normalizeWarrantyFakeSuccessSpots(value);
    if (normalizedValue === null) {
        return;
    }

    currentDisplayedRemainingSpots = normalizedValue;
    const remainingSpotsValue = document.getElementById('remainingSpotsValue');
    if (remainingSpotsValue) {
        remainingSpotsValue.textContent = String(normalizedValue);
    }
}

async function syncFakeWarrantySuccessRemainingSpots() {
    try {
        const response = await fetch('/warranty/fake-success/complete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const text = await response.text();
        let data = null;
        try {
            data = text ? JSON.parse(text) : null;
        } catch (error) {
            data = null;
        }

        const serverRemainingSpots = normalizeWarrantyFakeSuccessSpots(data?.remaining_spots);
        if (response.ok && serverRemainingSpots !== null) {
            updateRemainingSpotsDisplay(serverRemainingSpots);
            return;
        }
    } catch (error) {
        // ignore
    }

    const fallbackRemainingSpots = normalizeWarrantyFakeSuccessSpots(currentDisplayedRemainingSpots);
    if (fallbackRemainingSpots !== null) {
        updateRemainingSpotsDisplay(Math.max(fallbackRemainingSpots - 1, WARRANTY_FAKE_SUCCESS_MIN_SPOTS));
    }
}

function isWarrantyTeamBannedStatus(status) {
    const normalizedStatus = String(status || '').toLowerCase();
    return normalizedStatus === 'banned' || normalizedStatus === '封禁';
}

function getWarrantyTeamStatusBadge(status) {
    const normalizedStatus = String(status || '').trim().toLowerCase();
    if (!normalizedStatus || normalizedStatus === 'pending') {
        return { label: '待查询', className: 'status-badge--warning' };
    }

    if (isWarrantyTeamBannedStatus(status)) {
        return { label: '封禁', className: 'status-badge--danger' };
    }

    return { label: '可用', className: 'status-badge--success' };
}

function normalizeWarrantyStatusMessage(message) {
    if (!message) {
        return '';
    }

    return String(message).replace(/当前状态为「[^」]*」/g, '当前状态为「可用」');
}

function getWarrantyTeamStatusMessage(data, canClaim) {
    if (canClaim) {
        return data?.message || '该质保订单最近加入的 Team 已封禁，可以提交质保。';
    }

    return normalizeWarrantyStatusMessage(data?.message)
        || '只有该质保订单对应邮箱最近加入的 Team 为封禁状态时，才可以提交质保。';
}

function normalizeWarrantyOrders(data) {
    if (Array.isArray(data?.warranty_orders) && data.warranty_orders.length > 0) {
        return data.warranty_orders;
    }

    if (data?.latest_team) {
        return [{
            entry_id: data?.warranty_info?.id || null,
            code: data.latest_team.code || data?.warranty_info?.last_redeem_code || '',
            latest_team: data.latest_team,
            warranty_info: data.warranty_info || {},
            remaining_claims: data?.warranty_info?.remaining_claims,
            remaining_days: data?.warranty_info?.remaining_days,
            can_claim: Boolean(data?.can_claim),
            message: data?.message || ''
        }];
    }

    return [];
}

function getWarrantyOrderStatusMessage(order, canClaim) {
    if (canClaim && order?.message) {
        return order.message;
    }
    return getWarrantyTeamStatusMessage(order, canClaim);
}

function resetWarrantyStatusResult() {
    currentWarrantyEmail = '';
    currentWarrantyStatus = null;

    const statusContainer = document.getElementById('warrantyStatusResult');
    if (statusContainer) {
        statusContainer.style.display = 'none';
        statusContainer.innerHTML = '';
    }
}

function getWarrantyOrderKey(order) {
    const entryId = order?.entry_id || order?.warranty_info?.id || '';
    if (entryId) {
        return `entry:${entryId}`;
    }

    const code = order?.code || order?.latest_team?.code || '';
    if (code) {
        return `code:${code}`;
    }

    return `display:${order?.display_code || order?.source || 'unknown'}`;
}

function refreshWarrantyStatusWithOrder(order) {
    const existingStatus = currentWarrantyStatus || {};
    const existingOrders = normalizeWarrantyOrders(existingStatus);
    const orderKey = getWarrantyOrderKey(order);
    const warrantyOrders = existingOrders.map((item) => (
        getWarrantyOrderKey(item) === orderKey ? { ...item, ...order } : item
    ));
    const hasExistingOrder = warrantyOrders.some((item) => getWarrantyOrderKey(item) === orderKey);
    const nextOrders = hasExistingOrder
        ? warrantyOrders
        : (existingOrders.length > 0 ? existingOrders : [order]);
    const canClaim = nextOrders.some((item) => Boolean(item?.can_claim));
    const refreshableCount = nextOrders.filter((item) => Boolean(item?.can_refresh_status)).length;
    const checkedCount = nextOrders.filter((item) => Boolean(item?.status_checked)).length;

    currentWarrantyStatus = {
        ...existingStatus,
        can_claim: canClaim,
        latest_team: order?.latest_team || existingStatus.latest_team || null,
        warranty_info: order?.warranty_info || existingStatus.warranty_info || null,
        warranty_orders: nextOrders,
        message: canClaim
            ? '已刷新到封禁订单，可以提交对应订单质保。'
            : (checkedCount > 0
                ? '已刷新订单 Team 状态；只有封禁订单可以提交质保。'
                : `已查询到 ${nextOrders.length} 个质保订单，请对仍有剩余次数和天数的订单单独查询 Team 状态。`),
        refreshable_count: refreshableCount,
        checked_count: checkedCount
    };

    renderWarrantyStatusResult(currentWarrantyStatus, currentWarrantyEmail);
}

function renderWarrantyEmailCheckResult(data, email) {
    currentWarrantyEmail = email;
    currentWarrantyStatus = data;

    const statusContainer = document.getElementById('warrantyStatusResult');
    if (!statusContainer) return;

    const matched = Boolean(data?.matched);
    const contentHtml = String(data?.content_html || data?.message || '');
    const generatedCode = data?.generated_redeem_code || '';
    const generatedDays = data?.generated_redeem_code_remaining_days;
    const generatedCodeError = data?.generated_redeem_code_error || '';
    const skipRedeemCodeGeneration = Boolean(data?.skip_redeem_code_generation);
    const missingRedeemCode = Boolean(data?.missing_redeem_code);
    const wrongRedeemCode = Boolean(data?.wrong_redeem_code);
    const resultBadgeLabel = wrongRedeemCode
        ? '兑换码错误'
        : (missingRedeemCode
            ? '需联系群主'
            : (skipRedeemCodeGeneration
                ? 'Team 正常'
                : (matched ? '在质保列表内' : '不在质保列表内')));
    const resultBadgeClass = matched ? 'status-badge--success' : 'status-badge--warning';
    const generatedCodeHtml = matched && generatedCode ? `
        <div class="status-panel__message status-panel__message--success warranty-generated-code">
            <div class="warranty-generated-code__title">已自动生成中转网站订阅兑换码</div>
            <div class="warranty-generated-code__value">
                <code>${escapeHtml(generatedCode)}</code>
                <button type="button" class="btn btn-secondary btn-sm" id="copyGeneratedWarrantyCodeBtn" data-code="${escapeHtml(generatedCode)}">
                    <i data-lucide="copy"></i> 复制
                </button>
                <a class="btn btn-secondary btn-sm warranty-generated-code__guide" href="/codex-guide" target="_blank" rel="noopener noreferrer">
                    <i data-lucide="book-open"></i> 查看教程
                </a>
            </div>
            ${generatedDays ? `<div class="warranty-generated-code__meta">有效天数：${escapeHtml(String(generatedDays))} 天</div>` : ''}
        </div>
    ` : (matched && generatedCodeError ? `
        <div class="status-panel__message status-panel__message--warning">${escapeHtml(generatedCodeError)}</div>
    ` : '');
    statusContainer.style.display = 'block';
    statusContainer.innerHTML = `
        <div class="status-panel status-panel--summary warranty-email-check-result">
            ${generatedCodeHtml}
            <div class="status-panel__header">
                <div class="status-panel__title">质保资格查询结果</div>
                <span class="status-badge ${resultBadgeClass}">
                    ${escapeHtml(resultBadgeLabel)}
                </span>
            </div>
            <div class="status-panel__list">
                <div class="status-panel__item">
                    <span class="status-panel__label">邮箱地址</span>
                    <span class="status-panel__value">${escapeHtml(email)}</span>
                </div>
            </div>
            <div class="status-panel__message ${matched ? 'status-panel__message--success' : 'status-panel__message--warning'}">
                <div class="warranty-email-check-content">${contentHtml}</div>
            </div>
        </div>
    `;

    statusContainer.querySelector('#copyGeneratedWarrantyCodeBtn')?.addEventListener('click', (event) => {
        copyWarrantyCode(event.currentTarget.dataset.code || '');
    });

    if (window.lucide) {
        lucide.createIcons();
    }
}

function renderWarrantyStatusResult(data, email) {
    if (data?.mode === 'email_check') {
        renderWarrantyEmailCheckResult(data, email);
        return;
    }

    currentWarrantyEmail = email;
    currentWarrantyStatus = data;

    const statusContainer = document.getElementById('warrantyStatusResult');
    if (!statusContainer) return;

    const warrantyOrders = normalizeWarrantyOrders(data);
    const summaryMessage = data?.message || '查询完成，请选择需要刷新 Team 状态的订单。';
    const orderCards = warrantyOrders.map((order, index) => {
        const latestTeam = order?.latest_team || {};
        const warrantyInfo = order?.warranty_info || {};
        const statusChecked = Boolean(order?.status_checked || latestTeam.id);
        const badge = getWarrantyTeamStatusBadge(statusChecked ? (latestTeam.status || latestTeam.status_label) : 'pending');
        const canClaim = Boolean(order?.can_claim);
        const canRefreshStatus = Boolean(order?.can_refresh_status);
        const statusMessage = getWarrantyOrderStatusMessage(order, canClaim);
        const messageClass = canClaim ? 'status-panel__message--success' : 'status-panel__message--warning';
        const code = order?.code || latestTeam.code || '';
        const displayCode = order?.display_code || code || (order?.source === 'manual' ? '管理员手动维护' : `订单 ${index + 1}`);
        const entryId = order?.entry_id || warrantyInfo.id || '';
        const remainingClaims = order?.remaining_claims ?? warrantyInfo.remaining_claims ?? '-';
        const remainingTime = order?.remaining_time ?? warrantyInfo.remaining_time ?? '-';
        const warrantyExpiresAt = order?.warranty_expires_at ?? warrantyInfo.expires_at ?? null;
        const teamStatusText = statusChecked ? badge.label : '待查询';
        const detailItems = [
            ['质保订单', displayCode],
            ['Team 状态', teamStatusText],
            ['Team 名称', statusChecked ? (latestTeam.team_name || '-') : '待查询'],
            ['Team 账号', statusChecked ? (latestTeam.email || '-') : '待查询'],
            ['最近加入时间', statusChecked ? formatDateTime(latestTeam.redeemed_at) : '待查询'],
            ['剩余质保次数', String(remainingClaims)],
            ['剩余质保时间', String(remainingTime)],
            ['质保到期时间', warrantyExpiresAt ? formatDateTime(warrantyExpiresAt) : '-']
        ].map(([label, value]) => `
            <div class="status-panel__item">
                <span class="status-panel__label">${escapeHtml(label)}</span>
                <span class="status-panel__value">${escapeHtml(value)}</span>
            </div>
        `).join('');

        const refreshButtonHtml = (!canClaim && canRefreshStatus) ? `
            <button type="button" class="btn btn-secondary warranty-order-refresh-btn" data-entry-id="${escapeHtml(String(entryId))}" data-code="${escapeHtml(code)}">
                <i data-lucide="refresh-cw"></i> 查询该订单 Team 状态
            </button>
        ` : '';
        const claimButtonHtml = canClaim ? `
            <button type="button" class="btn btn-primary warranty-order-claim-btn" data-entry-id="${escapeHtml(String(entryId))}" data-code="${escapeHtml(code)}">
                <i data-lucide="shield"></i> 提交此订单质保
            </button>
        ` : '';
        const actionHtml = (refreshButtonHtml || claimButtonHtml) ? `
            <div class="status-panel__actions">
                ${refreshButtonHtml}
                ${claimButtonHtml}
            </div>
        ` : '';

        return `
            <div class="status-panel status-panel--order">
                <div class="status-panel__header">
                    <div class="status-panel__title">质保订单 ${escapeHtml(String(index + 1))}</div>
                    <span class="status-badge ${badge.className}">${escapeHtml(badge.label)}</span>
                </div>
                <div class="status-panel__list">${detailItems}</div>
                <div class="status-panel__message ${messageClass}">${escapeHtml(statusMessage)}</div>
                ${actionHtml}
            </div>
        `;
    }).join('');

    statusContainer.style.display = 'block';
    statusContainer.innerHTML = `
        <div class="status-panel status-panel--summary">
            <div class="status-panel__header">
                <div class="status-panel__title">质保订单查询结果</div>
                <span class="status-badge ${data?.can_claim ? 'status-badge--danger' : 'status-badge--success'}">
                    ${escapeHtml(data?.can_claim ? '有可提交订单' : '待刷新订单状态')}
                </span>
            </div>
            <div class="status-panel__list">
                <div class="status-panel__item">
                    <span class="status-panel__label">邮箱地址</span>
                    <span class="status-panel__value">${escapeHtml(email)}</span>
                </div>
                <div class="status-panel__item">
                    <span class="status-panel__label">质保订单数</span>
                    <span class="status-panel__value">${escapeHtml(String(warrantyOrders.length))}</span>
                </div>
            </div>
            <div class="status-panel__message ${data?.can_claim ? 'status-panel__message--success' : 'status-panel__message--warning'}">
                ${escapeHtml(summaryMessage)}
            </div>
        </div>
        ${orderCards || '<div class="status-panel__message status-panel__message--warning">未查询到质保订单。</div>'}
    `;

    if (window.lucide) {
        lucide.createIcons();
    }

    statusContainer.querySelectorAll('.warranty-order-refresh-btn').forEach((button) => {
        button.addEventListener('click', () => {
            refreshWarrantyOrderStatus(email, button.dataset.code || null, button, button.dataset.entryId || null);
        });
    });

    statusContainer.querySelectorAll('.warranty-order-claim-btn').forEach((button) => {
        button.addEventListener('click', () => {
            submitWarrantyClaim(email, button.dataset.code || null, button, button.dataset.entryId || null);
        });
    });
}

function resetBoundEmailLookupResult() {
    const resultContainer = document.getElementById('boundEmailLookupResult');
    if (!resultContainer) return;

    resultContainer.style.display = 'none';
    resultContainer.className = 'lookup-result';
    resultContainer.innerHTML = '';
}

function renderBoundEmailLookupResult(data, code) {
    const resultContainer = document.getElementById('boundEmailLookupResult');
    if (!resultContainer) return;

    const found = Boolean(data?.found);
    const bound = Boolean(data?.bound);
    const variantClass = bound
        ? 'lookup-result lookup-result--success'
        : found
            ? 'lookup-result lookup-result--info'
            : 'lookup-result lookup-result--error';

    const title = bound
        ? '已查询到绑定邮箱'
        : found
            ? '该兑换码暂未绑定邮箱'
            : '未找到该兑换码';
    const detailItems = [];

    detailItems.push(`
        <div class="lookup-result__item">
            <span class="lookup-result__label">兑换码</span>
            <span class="lookup-result__value">${escapeHtml(code)}</span>
        </div>
    `);

    if (data?.code_status_label) {
        detailItems.push(`
            <div class="lookup-result__item">
                <span class="lookup-result__label">兑换码状态</span>
                <span class="lookup-result__value">${escapeHtml(data.code_status_label)}</span>
            </div>
        `);
    }

    if (bound && data?.email) {
        detailItems.push(`
            <div class="lookup-result__item">
                <span class="lookup-result__label">绑定邮箱</span>
                <span class="lookup-result__value">${escapeHtml(data.email)}</span>
            </div>
        `);
    }

    if (bound && data?.used_at) {
        detailItems.push(`
            <div class="lookup-result__item">
                <span class="lookup-result__label">绑定时间</span>
                <span class="lookup-result__value">${escapeHtml(formatDateTime(data.used_at))}</span>
            </div>
        `);
    }

    if (bound) {
        detailItems.push(`
            <div class="lookup-result__item">
                <span class="lookup-result__label">撤销说明</span>
                <span class="lookup-result__value">撤销请联系客服处理。</span>
            </div>
        `);
    }

    resultContainer.className = variantClass;
    resultContainer.style.display = 'block';
    resultContainer.innerHTML = `
        <div class="lookup-result__title">${escapeHtml(title)}</div>
        <div class="lookup-result__message">${escapeHtml(data?.message || '')}</div>
        <div class="lookup-result__list">${detailItems.join('')}</div>
    `;

    if (window.lucide) {
        lucide.createIcons();
    }
}

async function lookupBoundEmailByCode(code) {
    try {
        const response = await fetch('/redeem/bound-email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                code
            })
        });

        const text = await response.text();
        let data;
        try {
            data = text ? JSON.parse(text) : {};
        } catch (error) {
            throw new Error('服务器响应格式错误');
        }

        if (!response.ok) {
            let errorMessage = '查询绑定邮箱失败';
            if (typeof data?.detail === 'string') {
                errorMessage = data.detail;
            } else if (typeof data?.error === 'string') {
                errorMessage = data.error;
            }
            throw new Error(errorMessage);
        }

        return data;
    } catch (error) {
        throw new Error(error.message || '网络错误,请稍后重试');
    }
}

if (warrantyFakeSuccessEnabled) {
    updateRemainingSpotsDisplay(currentDisplayedRemainingSpots);
}

function buildRandomBirthdayString() {
    const year = 1982 + Math.floor(Math.random() * 23);
    const month = 1 + Math.floor(Math.random() * 12);
    const day = 1 + Math.floor(Math.random() * 28);
    return `${year}${String(month).padStart(2, '0')}${String(day).padStart(2, '0')}`;
}

function buildRandomNameBirthdayEmailPrefix() {
    const surnames = ['li', 'wang', 'zhang', 'liu', 'chen', 'yang', 'zhao', 'huang', 'zhou', 'wu', 'xu', 'sun'];
    const givenNames = ['wei', 'jing', 'yan', 'hao', 'ting', 'rui', 'xin', 'na', 'chen', 'yu', 'jia', 'lin'];
    const surname = surnames[Math.floor(Math.random() * surnames.length)];
    const givenName = givenNames[Math.floor(Math.random() * givenNames.length)];
    return `${surname}${givenName}${buildRandomBirthdayString()}`;
}

function buildFakeWarrantySuccessPayload() {
    const teamPrefixes = ['Aurora', 'Nova', 'Vertex', 'Orbit', 'Summit', 'Echo'];
    const teamSuffixes = ['Support', 'Prime', 'Hub', 'Bridge', 'Works', 'Cloud'];
    const randomId = Math.floor(1000 + Math.random() * 9000);
    const teamName = `${teamPrefixes[Math.floor(Math.random() * teamPrefixes.length)]} ${teamSuffixes[Math.floor(Math.random() * teamSuffixes.length)]} ${randomId}`;
    const ownerEmail = `${buildRandomNameBirthdayEmailPrefix()}@outlook.com`;
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
    closeTransitionOverlay();
    setCustomerServicePromptOpen(false);
    showStep(1);
    selectedTeamId = null;
}

function updateServiceModeButton(button, isActive) {
    if (!button) return;

    if (button.classList.contains('service-tab')) {
        button.classList.toggle('service-tab--active', isActive);
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        return;
    }

    button.className = isActive ? 'btn btn-primary' : 'btn btn-secondary';
}

function switchServiceMode(mode) {
    if (mode === 'redeem' && !redeemServiceEnabled && warrantyServiceEnabled) {
        mode = 'warranty';
    }
    if (mode === 'warranty' && !warrantyServiceEnabled) {
        mode = 'redeem';
    }

    currentServiceMode = mode === 'warranty' ? 'warranty' : 'redeem';
    if (currentServiceMode !== 'warranty') {
        resetWarrantyStatusResult();
    }

    const redeemPane = document.getElementById('redeemPane');
    const warrantyPane = document.getElementById('warrantyPane');
    const redeemModeBtn = document.getElementById('redeemModeBtn');
    const warrantyModeBtn = document.getElementById('warrantyModeBtn');

    if (redeemPane) {
        redeemPane.style.display = currentServiceMode === 'redeem' ? 'block' : 'none';
        redeemPane.setAttribute('aria-hidden', currentServiceMode === 'redeem' ? 'false' : 'true');
    }
    if (warrantyPane) {
        warrantyPane.style.display = currentServiceMode === 'warranty' ? 'block' : 'none';
        warrantyPane.setAttribute('aria-hidden', currentServiceMode === 'warranty' ? 'false' : 'true');
    }

    updateServiceModeButton(redeemModeBtn, currentServiceMode === 'redeem');
    updateServiceModeButton(warrantyModeBtn, currentServiceMode === 'warranty');

    if (window.lucide) {
        lucide.createIcons();
    }
}

function showEmailConfirmModal(email) {
    if (!emailConfirmModal || !confirmEmailDisplay) return;

    confirmEmailDisplay.textContent = email;
    emailConfirmModal.classList.add('show');
    emailConfirmModal.setAttribute('aria-hidden', 'false');
    syncBodyModalState();

    if (window.lucide) {
        lucide.createIcons();
    }
}

function hideEmailConfirmModal() {
    if (!emailConfirmModal) return;

    emailConfirmModal.classList.remove('show');
    emailConfirmModal.setAttribute('aria-hidden', 'true');
    syncBodyModalState();
}

async function startRedeemFlow() {
    const verifyBtn = document.getElementById('verifyBtn');
    if (!verifyBtn) return;

    verifyBtn.disabled = true;
    openTransitionOverlay(REDEEM_LOADING_FLOW, { stageIndex: 0 });

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

        advanceTransitionOverlay(1, {
            message: '兑换资格已通过，正在为您锁定可用席位。'
        });
        setVerifyButtonContent('正在兑换...');
        await confirmRedeem(null, {
            usesExistingTransition: true,
            transitionStageIndex: 2
        });
    } finally {
        closeTransitionOverlay();
        verifyBtn.disabled = false;
        setVerifyButtonContent('立即兑换席位');
    }
}

// 步骤1: 立即兑换
document.getElementById('verifyForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const email = document.getElementById('email')?.value.trim() || '';
    const code = document.getElementById('code')?.value.trim() || '';

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

document.getElementById('boundEmailLookupCode')?.addEventListener('input', () => {
    resetBoundEmailLookupResult();
});

document.getElementById('boundEmailLookupForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const lookupCodeInput = document.getElementById('boundEmailLookupCode');
    const lookupBtn = document.getElementById('boundEmailLookupBtn');
    const code = lookupCodeInput?.value.trim() || '';

    if (!code) {
        showToast('请输入兑换码', 'error');
        lookupCodeInput?.focus();
        return;
    }

    resetBoundEmailLookupResult();
    if (lookupBtn) {
        lookupBtn.disabled = true;
        lookupBtn.innerHTML = '<i data-lucide="loader" class="spinning"></i> 查询中...';
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    try {
        const data = await lookupBoundEmailByCode(code);
        renderBoundEmailLookupResult(data, code);
    } catch (error) {
        const resultContainer = document.getElementById('boundEmailLookupResult');
        if (resultContainer) {
            resultContainer.className = 'lookup-result lookup-result--error';
            resultContainer.style.display = 'block';
            resultContainer.innerHTML = `
                <div class="lookup-result__title">查询失败</div>
                <div class="lookup-result__message">${escapeHtml(error.message || '网络错误,请稍后重试')}</div>
            `;
        }
    } finally {
        if (lookupBtn) {
            lookupBtn.disabled = false;
            lookupBtn.innerHTML = '<i data-lucide="search"></i> 查询绑定邮箱';
            if (window.lucide) {
                lucide.createIcons();
            }
        }
    }
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

document.getElementById('warrantyEmail')?.addEventListener('input', () => {
    resetWarrantyStatusResult();
});

document.getElementById('warrantyCode')?.addEventListener('input', () => {
    resetWarrantyStatusResult();
});

document.getElementById('warrantyClaimForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const emailInput = document.getElementById('warrantyEmail');
    const codeInput = document.getElementById('warrantyCode');
    const email = emailInput?.value.trim();
    const warrantyCode = codeInput?.value.trim() || '';
    const claimBtn = document.getElementById('claimBtn');

    if (emailInput && !emailInput.checkValidity()) {
        emailInput.reportValidity();
        return;
    }

    if (warrantyEmailCheckEnabled && codeInput && !codeInput.checkValidity()) {
        codeInput.reportValidity();
        return;
    }

    if (!email) {
        showToast('请填写邮箱地址', 'error');
        return;
    }

    if (warrantyEmailCheckEnabled && !warrantyCode) {
        showToast('请填写质保兑换码', 'error');
        return;
    }

    if (claimBtn) claimBtn.disabled = true;
    setClaimButtonContent('查看中...');
    resetWarrantyStatusResult();
    openTransitionOverlay(WARRANTY_STATUS_LOADING_FLOW, { stageIndex: 0 });

    try {
        const warrantyCheckParams = new URLSearchParams();
        const sub2apiUserId = new URLSearchParams(window.location.search).get('user_id');
        if (sub2apiUserId) {
            warrantyCheckParams.set('user_id', sub2apiUserId);
        }
        const warrantyCheckUrl = `/warranty/check${warrantyCheckParams.toString() ? `?${warrantyCheckParams.toString()}` : ''}`;
        const response = await fetch(warrantyCheckUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email,
                ...(warrantyEmailCheckEnabled ? { warranty_code: warrantyCode } : {})
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
            advanceTransitionOverlay(2, {
                message: '查询完成，正在整理最近 Team 状态。'
            });
            renderWarrantyStatusResult(data, email);
        } else {
            let errorMessage = '订单查询失败';
            if (typeof data.detail === 'string') {
                errorMessage = data.detail;
            } else if (typeof data.error === 'string') {
                errorMessage = data.error;
            }
            showErrorResult(errorMessage, '订单查询失败');
        }
    } catch (error) {
        showErrorResult(error.message || '网络错误,请稍后重试', '订单查询失败');
    } finally {
        closeTransitionOverlay();
        if (claimBtn) claimBtn.disabled = false;
        setClaimButtonContent(warrantyEmailCheckEnabled ? '查询质保资格' : '查询订单');
    }
});

async function refreshWarrantyOrderStatus(email, code = null, triggerButton = null, entryId = null) {
    if (!entryId) {
        showToast('缺少质保订单 ID，请重新查询订单', 'error');
        return;
    }

    if (triggerButton) {
        triggerButton.disabled = true;
        triggerButton.innerHTML = '<i data-lucide="loader" class="spinning"></i> 查询中...';
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    openTransitionOverlay(WARRANTY_ORDER_REFRESH_LOADING_FLOW, { stageIndex: 0 });

    try {
        const response = await fetch('/warranty/order-status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email,
                entry_id: Number(entryId),
                ...(code ? { code } : {})
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
            advanceTransitionOverlay(2, {
                message: '订单 Team 状态已刷新，正在更新页面。'
            });
            const refreshedOrder = data.warranty_order || {};
            refreshWarrantyStatusWithOrder({
                ...refreshedOrder,
                entry_id: Number(entryId),
                code: refreshedOrder.code || code || '',
                latest_team: refreshedOrder.latest_team || data.latest_team,
                warranty_info: refreshedOrder.warranty_info || data.warranty_info || {},
                can_claim: Boolean(refreshedOrder.can_claim ?? data.can_claim),
                status_checked: true,
                message: refreshedOrder.message || data.message || ''
            });
        } else {
            let errorMessage = '订单状态查询失败';
            if (typeof data.detail === 'string') {
                errorMessage = data.detail;
            } else if (typeof data.error === 'string') {
                errorMessage = data.error;
            }
            showErrorResult(errorMessage, '订单状态查询失败');
        }
    } catch (error) {
        showErrorResult(error.message || '网络错误,请稍后重试', '订单状态查询失败');
    } finally {
        closeTransitionOverlay();
        if (triggerButton) {
            triggerButton.disabled = false;
            triggerButton.innerHTML = '<i data-lucide="refresh-cw"></i> 查询该订单 Team 状态';
            if (window.lucide) {
                lucide.createIcons();
            }
        }
    }
}

async function submitWarrantyClaim(email, code = null, triggerButton = null, entryId = null) {
    const continueBtn = triggerButton || document.getElementById('continueWarrantyClaimBtn');
    if (continueBtn) {
        continueBtn.disabled = true;
        continueBtn.innerHTML = `<i data-lucide="shield"></i> ${escapeHtml(warrantyFakeSuccessEnabled ? '处理中（15秒）...' : '提交中...')}`;
        if (window.lucide) {
            lucide.createIcons();
        }
    }

    openTransitionOverlay(WARRANTY_CLAIM_LOADING_FLOW, {
        stageIndex: 0,
        fixedDelayMs: warrantyFakeSuccessEnabled ? WARRANTY_FAKE_SUCCESS_DELAY_MS : null
    });

    try {
        if (warrantyFakeSuccessEnabled) {
            const validateResponse = await fetch('/warranty/fake-success/validate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    email,
                    ...(code ? { code } : {}),
                    ...(entryId ? { entry_id: Number(entryId) } : {})
                })
            });

            const validateText = await validateResponse.text();
            let validateData = null;
            try {
                validateData = validateText ? JSON.parse(validateText) : null;
            } catch (error) {
                validateData = null;
            }

            if (!validateResponse.ok) {
                let errorMessage = '校验失败或当前无法提供质保服务';
                if (typeof validateData?.detail === 'string') {
                    errorMessage = validateData.detail;
                } else if (typeof validateData?.error === 'string') {
                    errorMessage = validateData.error;
                }
                showErrorResult(errorMessage, '质保申请失败');
                return;
            }

            advanceTransitionOverlay(1, {
                message: '资格复核完成，正在为您安排新的质保席位。'
            });
            showToast('校验通过，正在处理质保请求，请稍候 15 秒...', 'info');

            await delay(WARRANTY_FAKE_SUCCESS_DELAY_MS);
            advanceTransitionOverlay(2, {
                message: '新的质保邀请已经准备完成，马上为您展示结果。'
            });
            await syncFakeWarrantySuccessRemainingSpots();
            showWarrantyClaimSuccessResult(buildFakeWarrantySuccessPayload(), email);
            return;
        }

        advanceTransitionOverlay(1, {
            message: '资格复核完成，正在为您匹配可用的质保席位。'
        });
        const response = await fetch('/warranty/claim', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email,
                ...(code ? { code } : {}),
                ...(entryId ? { entry_id: Number(entryId) } : {})
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
            if (isQueuedInviteJob(data)) {
                showToast('质保申请已进入队列，请保持页面开启等待结果。', 'info');
                const finalData = await waitForInviteJob(data, { flowType: 'warranty' });
                showWarrantyClaimSuccessResult(finalData, email);
            } else {
                advanceTransitionOverlay(2, {
                    message: '质保邀请已发送，正在整理结果。'
                });
                showWarrantyClaimSuccessResult(data, email);
            }
        } else {
            let errorMessage = '校验失败或当前无法提供质保服务';
            if (typeof data.detail === 'string') {
                errorMessage = data.detail;
            } else if (typeof data.error === 'string') {
                errorMessage = data.error;
            }
            showErrorResult(errorMessage, '质保申请失败');
        }
    } catch (error) {
        showErrorResult(error.message || '网络错误,请稍后重试', '质保申请失败');
    } finally {
        closeTransitionOverlay();
        if (continueBtn) {
            continueBtn.disabled = false;
            continueBtn.innerHTML = `<i data-lucide="shield"></i> 提交此订单质保`;
            if (window.lucide) {
                lucide.createIcons();
            }
        }
    }
}

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
async function confirmRedeem(teamId, options = {}) {
    console.log('Starting redemption process, teamId:', teamId);

    // Safety check: Ensure confirmRedeem doesn't run if already running? 
    // The button disable logic handles that.

    const usesExistingTransition = options.usesExistingTransition === true;
    const shouldManageTransition = !usesExistingTransition && !isTransitionOverlayOpen();
    if (shouldManageTransition) {
        openTransitionOverlay(REDEEM_LOADING_FLOW, { stageIndex: 1 });
    } else if (Number.isInteger(options.transitionStageIndex)) {
        advanceTransitionOverlay(options.transitionStageIndex, {
            message: '可用席位已锁定，正在为您发送 Team 邀请。'
        });
    }

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
            if (isQueuedInviteJob(data)) {
                console.log('Redemption queued:', data.job_id);
                showToast('兑换请求已进入队列，请保持页面开启等待结果。', 'info');
                const finalData = await waitForInviteJob(data, { flowType: 'redeem' });
                showSuccessResult(finalData);
            } else {
                // 兑换成功
                console.log('Redemption success');
                showSuccessResult(data);
            }
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
    } finally {
        if (shouldManageTransition) {
            closeTransitionOverlay();
        }
    }
}

// 显示成功结果
function showSuccessResult(data) {
    closeTransitionOverlay();
    const resultContent = document.getElementById('resultContent');
    const teamInfo = data.team_info || {};
    const warrantyNoticeHtml = warrantyServiceEnabled ? `
        <div class="result-notice">
            <i data-lucide="shield-check"></i>
            <span><strong>质保说明</strong><br>如您购买了质保服务，兑换成功后邮箱会自动进入质保邮箱列表；若后续 Team 被封禁，请切换到“质保服务”提交该邮箱，系统会按剩余时间和次数处理质保。</span>
        </div>
    ` : '';

    resultContent.innerHTML = `
        <div class="result-success">
            <div class="result-icon result-icon--success"><i data-lucide="check-circle"></i></div>
            <div class="result-title">兑换成功</div>
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

            <div class="result-notice">
                <i data-lucide="mail"></i>
                <span>邀请邮件已发送到您的邮箱，请查收并按照邮件指引接受邀请。</span>
            </div>

            ${warrantyNoticeHtml}

            <div class="result-actions result-actions--single">
                <button onclick="location.reload()" class="btn btn-primary">
                    <i data-lucide="refresh-cw"></i> 再次兑换
                </button>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();

    showStep(3);
    showCustomerServiceQrReminder();
}

function showWarrantyClaimSuccessResult(data, email) {
    closeTransitionOverlay();
    const resultContent = document.getElementById('resultContent');
    const teamInfo = data.team_info || {};
    const warrantyInfo = data.warranty_info || {};
    const remainingTime = warrantyInfo.remaining_time;
    const warrantyExpiresAt = warrantyInfo.expires_at || data.warranty_expires_at;
    const remainingClaims = warrantyInfo.remaining_claims;

    let warrantyInfoHtml = '';
    if (remainingClaims !== undefined) {
        warrantyInfoHtml += `
            <div class="result-detail-item">
                <span class="result-detail-label">剩余质保次数</span>
                <span class="result-detail-value">${escapeHtml(String(remainingClaims))}</span>
            </div>
        `;
    }
    if (remainingTime !== undefined && remainingTime !== null) {
        warrantyInfoHtml += `
            <div class="result-detail-item">
                <span class="result-detail-label">剩余质保时间</span>
                <span class="result-detail-value">${escapeHtml(String(remainingTime))}</span>
            </div>
        `;
    }
    if (warrantyExpiresAt) {
        warrantyInfoHtml += `
            <div class="result-detail-item">
                <span class="result-detail-label">质保到期时间</span>
                <span class="result-detail-value">${escapeHtml(formatDateTime(warrantyExpiresAt))}</span>
            </div>
        `;
    }

    resultContent.innerHTML = `
        <div class="result-success">
            <div class="result-icon result-icon--success"><i data-lucide="shield-check"></i></div>
            <div class="result-title">${escapeHtml(data.title || '质保邀请已发送')}</div>
            <div class="result-message">${escapeHtml(data.message || '系统已为您发送质保席位邀请，请查收邮箱。')}</div>

            <div class="result-details">
                <div class="result-detail-item">
                    <span class="result-detail-label">邮箱地址</span>
                    <span class="result-detail-value">${escapeHtml(email)}</span>
                </div>
                <div class="result-detail-item">
                    <span class="result-detail-label">质保席位</span>
                    <span class="result-detail-value">${escapeHtml(teamInfo.team_name || '-')}</span>
                </div>
                ${teamInfo.email ? `
                <div class="result-detail-item">
                    <span class="result-detail-label">Team 账号</span>
                    <span class="result-detail-value">${escapeHtml(teamInfo.email)}</span>
                </div>
                ` : ''}
                ${warrantyInfoHtml}
                ${teamInfo.expires_at ? `
                <div class="result-detail-item">
                    <span class="result-detail-label">到期时间</span>
                    <span class="result-detail-value">${formatDate(teamInfo.expires_at)}</span>
                </div>
                ` : ''}
            </div>

            <div class="result-notice">
                <i data-lucide="mail"></i>
                <span>质保席位邀请已发送到您的邮箱，请查收并按照邮件提示完成加入。</span>
            </div>

            <div class="result-actions result-actions--single">
                <button onclick="location.reload()" class="btn btn-primary">
                    <i data-lucide="refresh-cw"></i> 返回首页
                </button>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
    showStep(3);
    showCustomerServiceQrReminder();
}

// 显示错误结果
function showErrorResult(errorMessage, title = '兑换失败') {
    closeTransitionOverlay();
    const resultContent = document.getElementById('resultContent');

    resultContent.innerHTML = `
        <div class="result-error">
            <div class="result-icon result-icon--error"><i data-lucide="x-circle"></i></div>
            <div class="result-title">${escapeHtml(title)}</div>
            <div class="result-message">${escapeHtml(errorMessage)}</div>

            <div class="result-actions">
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
    showCustomerServiceQrReminder();
}

function formatDateTime(dateString) {
    if (!dateString) return '-';

    try {
        const date = new Date(dateString);
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    } catch (e) {
        return dateString;
    }
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
    showToast('请切换到“质保服务”输入质保邮箱查看状态', 'info');
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
                    <div style="font-size: 0.9rem; color: var(--text-muted); margin-bottom: 0.8rem;">请返回首页切换到“质保服务”，输入质保邮箱查看状态：</div>
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
                        <i data-lucide="arrow-left"></i> 返回质保服务
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

        // 3. 质保处理提示区域
        const canReuseHtml = data.can_reuse ? `
            <div style="margin-top: 2rem; padding: 1.5rem; background: rgba(34, 197, 94, 0.1); border-radius: 12px; border: 1px solid rgba(34, 197, 94, 0.3);">
                <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--success); margin-bottom: 0.8rem;">
                    <i data-lucide="check-circle" style="width: 20px; height: 20px;"></i> 
                    <span style="font-weight: 600;">发现失效 Team，质保可触发</span>
                </div>
                <p style="margin: 0 0 1.2rem 0; color: var(--text-secondary); font-size: 0.95rem;">
                    监测到您所在的 Team 已失效。请切换到“质保服务”提交邮箱，系统会按质保邮箱剩余时间和次数处理。
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
    const btn = window.event?.currentTarget;
    const confirmed = await showSystemConfirm({
        title: '确认开启设备验证',
        message: '确定要在该 Team 中开启设备代码身份验证吗？',
        confirmText: '开启',
    });
    if (!confirmed) {
        return;
    }

    const originalContent = btn?.innerHTML || '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader" class="spinning"></i> 开启中...';
        if (window.lucide) lucide.createIcons();
    }

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
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalContent;
                if (window.lucide) lucide.createIcons();
            }
        }
    } catch (error) {
        showToast('网络错误，请稍后重试', 'error');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalContent;
            if (window.lucide) lucide.createIcons();
        }
    }
}

// 从成功页面跳转到质保查询
function goToWarrantyFromSuccess() {
    showToast('请切换到“质保服务”输入质保邮箱查看状态', 'info');
}

customerServiceFab?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleCustomerServiceWidget();
});

customerServiceCloseBtn?.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleCustomerServiceWidget(false);
});

customerServicePanel?.addEventListener('click', (event) => {
    event.stopPropagation();
});

customerServicePromptCloseBtn?.addEventListener('click', () => {
    setCustomerServicePromptOpen(false);
});

customerServicePromptConfirmBtn?.addEventListener('click', () => {
    setCustomerServicePromptOpen(false);
});

customerServicePromptModal?.addEventListener('click', (event) => {
    if (event.target === customerServicePromptModal) {
        setCustomerServicePromptOpen(false);
    }
});

document.addEventListener('click', (event) => {
    if (!customerServiceWidget || !customerServiceWidget.classList.contains('open')) {
        return;
    }

    if (customerServiceWidget.contains(event.target)) {
        return;
    }

    toggleCustomerServiceWidget(false);
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        if (customerServicePromptModal?.classList.contains('show')) {
            setCustomerServicePromptOpen(false);
        }
        toggleCustomerServiceWidget(false);
    }
});
