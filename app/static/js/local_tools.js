const LOCAL_STORAGE_KEY = 'local_tools_items_v1';
const REFRESH_CONCURRENCY = 4;
const REFRESH_TIMEOUT_MS = 6000;

const batchContentInput = document.getElementById('batchContentInput');
const importFeedback = document.getElementById('importFeedback');
const importLocalToolsBtn = document.getElementById('importLocalToolsBtn');
const clearTextareaBtn = document.getElementById('clearTextareaBtn');
const clearLocalDataBtn = document.getElementById('clearLocalDataBtn');
const refreshAllSiteInfoBtn = document.getElementById('refreshAllSiteInfoBtn');
const fileInput = document.getElementById('localToolsFileInput');
const itemsGrid = document.getElementById('itemsGrid');
const emptyState = document.getElementById('emptyState');
const totalItemsValue = document.getElementById('totalItemsValue');
const visibleItemsValue = document.getElementById('visibleItemsValue');
const lastSavedAtValue = document.getElementById('lastSavedAtValue');
const searchInput = document.getElementById('localToolsSearchInput');
const invalidLinesBox = document.getElementById('invalidLinesBox');
const invalidLinesList = document.getElementById('invalidLinesList');

let currentItems = Object.freeze([]);
let currentInvalidLines = Object.freeze([]);
let currentSavedAt = '';

function setFeedback(message, tone = '') {
    importFeedback.textContent = message;
    importFeedback.className = 'feedback';
    if (tone) {
        importFeedback.classList.add(`feedback--${tone}`);
    }
}

function setRefreshButtonState(label, disabled) {
    if (!refreshAllSiteInfoBtn) {
        return;
    }

    refreshAllSiteInfoBtn.textContent = label;
    refreshAllSiteInfoBtn.disabled = disabled;
}

function formatSavedAt(value) {
    if (!value) {
        return '暂无';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '暂无';
    }

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatCheckedAt(value) {
    if (!value) {
        return '未刷新';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '未刷新';
    }

    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function extractTitleFromHtml(html) {
    const match = String(html || '').match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    if (!match) {
        return '';
    }

    return match[1].replace(/\s+/g, ' ').trim();
}

function buildDisplayUrl(url) {
    try {
        const parsed = new URL(url);
        return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
    } catch (_error) {
        return '';
    }
}

function normalizeCopyIdentifier(identifier) {
    return String(identifier || '').replace(/^\+1(?:[\s-])?/, '').trim();
}

function buildSiteInfo(openUrl, overrides = {}) {
    try {
        const parsed = new URL(openUrl);
        const path = `${parsed.pathname || '/'}${parsed.search ? `?参数 ${parsed.searchParams.size}` : ''}`;
        return Object.freeze({
            host: parsed.hostname || parsed.host || '未知站点',
            path,
            title: '',
            codeText: '待刷新',
            sourceText: '',
            expiresAt: '',
            statusText: '待刷新',
            checkedAt: '',
            ...overrides,
        });
    } catch (_error) {
        return Object.freeze({
            host: '未知站点',
            path: '/',
            title: '',
            codeText: '地址解析失败',
            sourceText: '',
            expiresAt: '',
            statusText: '地址解析失败',
            checkedAt: '',
            ...overrides,
        });
    }
}

function normalizeReadableText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function extractReadablePageContent(rawText, contentType) {
    const normalizedContentType = String(contentType || '').toLowerCase();

    if (normalizedContentType.includes('text/html')) {
        try {
            const parser = new DOMParser();
            const doc = parser.parseFromString(String(rawText || ''), 'text/html');
            return {
                title: normalizeReadableText(doc.title),
                text: normalizeReadableText(doc.body?.textContent || ''),
            };
        } catch (_error) {
            return {
                title: extractTitleFromHtml(rawText),
                text: normalizeReadableText(rawText),
            };
        }
    }

    return {
        title: '',
        text: normalizeReadableText(rawText),
    };
}

function parseVerificationContent(text) {
    const normalizedText = normalizeReadableText(text);
    const expiresMatch = normalizedText.match(/到期时间[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})/);
    const codeMatch = normalizedText.match(/(^|[^\d])(\d{6})(?!\d)/);
    const hasNoCode = normalizedText.includes('暂无验证码');

    const pipeSegments = normalizedText
        .split('|')
        .map((segment) => segment.trim())
        .filter(Boolean);

    let sourceText = '';
    const bracketSegment = pipeSegments.find((segment) => /^\(.+\)$/.test(segment));
    if (bracketSegment) {
        sourceText = bracketSegment.replace(/^\(|\)$/g, '').trim();
    } else {
        const fallbackSourceMatch = normalizedText.match(/\(([^()]{1,80})\)/);
        sourceText = fallbackSourceMatch ? fallbackSourceMatch[1].trim() : '';
    }

    if (hasNoCode) {
        return Object.freeze({
            codeText: '暂无验证码',
            sourceText,
            expiresAt: expiresMatch ? expiresMatch[1] : '',
            statusText: '未获取到验证码',
        });
    }

    if (codeMatch) {
        return Object.freeze({
            codeText: codeMatch[2],
            sourceText,
            expiresAt: expiresMatch ? expiresMatch[1] : '',
            statusText: '已获取验证码',
        });
    }

    return Object.freeze({
        codeText: '',
        sourceText,
        expiresAt: expiresMatch ? expiresMatch[1] : '',
        statusText: '',
    });
}

function createFrozenItems(items) {
    return Object.freeze(items.map((item, index) => Object.freeze({
        sequence: Number.isInteger(item.sequence) ? item.sequence : index + 1,
        identifier: String(item.identifier || ''),
        openUrl: String(item.openUrl || ''),
        displayUrl: String(item.displayUrl || buildDisplayUrl(item.openUrl || '')),
        siteInfo: buildSiteInfo(item.openUrl || '', item.siteInfo || {}),
    })));
}

function loadLocalState() {
    try {
        const rawValue = window.localStorage.getItem(LOCAL_STORAGE_KEY);
        if (!rawValue) {
            return;
        }

        const parsedValue = JSON.parse(rawValue);
        const parsedItems = Array.isArray(parsedValue?.items) ? parsedValue.items : [];
        currentItems = createFrozenItems(
            parsedItems.filter((item) =>
                typeof item?.identifier === 'string' &&
                typeof item?.openUrl === 'string'
            )
        );
        currentSavedAt = typeof parsedValue?.savedAt === 'string' ? parsedValue.savedAt : '';
        currentInvalidLines = Object.freeze([]);
    } catch (_error) {
        currentItems = Object.freeze([]);
        currentSavedAt = '';
        currentInvalidLines = Object.freeze([]);
        setFeedback('读取本地数据失败，已忽略旧数据。', 'warning');
    }
}

function persistLocalState(items) {
    const savedAt = new Date().toISOString();
    const storagePayload = {
        savedAt,
        items: items.map((item) => ({
            sequence: item.sequence,
            identifier: item.identifier,
            openUrl: item.openUrl,
            displayUrl: item.displayUrl,
            siteInfo: item.siteInfo,
        })),
    };

    window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(storagePayload));
    currentItems = createFrozenItems(items);
    currentSavedAt = savedAt;
}

function clearLocalState() {
    window.localStorage.removeItem(LOCAL_STORAGE_KEY);
    currentItems = Object.freeze([]);
    currentInvalidLines = Object.freeze([]);
    currentSavedAt = '';
}

function parseBatchContent(content) {
    const normalizedLines = String(content || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line);

    const parseResult = normalizedLines.reduce((result, line, index) => {
        const parts = line.split(/\s*-{4,}\s*/);
        if (parts.length < 2) {
            return {
                ...result,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: '缺少有效分隔符 ----' }]),
            };
        }

        const identifier = (parts[0] || '').trim();
        const openUrl = parts.slice(1).join('----').trim();

        if (!identifier) {
            return {
                ...result,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: '标识为空' }]),
            };
        }

        try {
            const parsedUrl = new URL(openUrl);
            if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
                throw new Error('invalid-protocol');
            }

            const nextItem = Object.freeze({
                sequence: result.items.length + 1,
                identifier,
                openUrl,
                displayUrl: buildDisplayUrl(openUrl),
                siteInfo: buildSiteInfo(openUrl),
            });

            return {
                items: result.items.concat([nextItem]),
                invalidLines: result.invalidLines,
            };
        } catch (_error) {
            return {
                ...result,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: '地址不是有效的 http/https URL' }]),
            };
        }
    }, { items: [], invalidLines: [] });

    return Object.freeze({
        items: createFrozenItems(parseResult.items),
        invalidLines: Object.freeze(parseResult.invalidLines.map((item) => Object.freeze(item))),
    });
}

async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }

    const tempInput = document.createElement('input');
    tempInput.value = text;
    tempInput.setAttribute('readonly', 'readonly');
    tempInput.style.position = 'absolute';
    tempInput.style.left = '-9999px';
    document.body.appendChild(tempInput);
    tempInput.select();
    document.execCommand('copy');
    document.body.removeChild(tempInput);
}

function renderInvalidLines(invalidLines) {
    invalidLinesList.innerHTML = '';

    if (!invalidLines.length) {
        invalidLinesBox.hidden = true;
        return;
    }

    invalidLines.forEach((item) => {
        const line = document.createElement('li');
        line.textContent = `第 ${item.lineNumber} 行：${item.reason}`;
        invalidLinesList.appendChild(line);
    });

    invalidLinesBox.hidden = false;
}

function createButton(className, text, title, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = text;
    button.title = title;
    button.addEventListener('click', onClick);
    return button;
}

function buildSiteSummaryText(siteInfo) {
    if (siteInfo.codeText) {
        return siteInfo.codeText;
    }

    if (siteInfo.title) {
        return siteInfo.title;
    }

    return siteInfo.statusText || '待刷新';
}

function buildSearchableText(item) {
    return [
        item.identifier,
        item.displayUrl,
        item.siteInfo.host,
        item.siteInfo.path,
        item.siteInfo.title,
        item.siteInfo.codeText,
        item.siteInfo.sourceText,
        item.siteInfo.expiresAt,
        item.siteInfo.statusText,
    ].join(' ').toLowerCase();
}

function createMetaLine(label, value) {
    const line = document.createElement('div');
    line.className = 'work-item__meta-line';

    const strong = document.createElement('strong');
    strong.textContent = `${label}：`;

    const text = document.createTextNode(value);

    line.append(strong, text);
    return line;
}

function renderItems() {
    const keyword = (searchInput.value || '').trim().toLowerCase();
    const filteredItems = currentItems.filter((item) => !keyword || buildSearchableText(item).includes(keyword));

    itemsGrid.innerHTML = '';
    totalItemsValue.textContent = String(currentItems.length);
    visibleItemsValue.textContent = String(filteredItems.length);
    lastSavedAtValue.textContent = formatSavedAt(currentSavedAt);

    renderInvalidLines(currentInvalidLines);

    if (!currentItems.length) {
        emptyState.hidden = false;
        itemsGrid.hidden = true;
        return;
    }

    emptyState.hidden = true;
    itemsGrid.hidden = false;

    filteredItems.forEach((item) => {
        const itemCard = document.createElement('article');
        itemCard.className = 'work-item';
        itemCard.title = `标识：${item.identifier}\n地址：${item.displayUrl}\n站点：${item.siteInfo.host}`;

        const copyButton = createButton(
            'work-item__copy',
            item.identifier,
            `点击复制：${normalizeCopyIdentifier(item.identifier) || item.identifier}`,
            async () => {
                const copiedText = normalizeCopyIdentifier(item.identifier) || item.identifier;
                await copyText(copiedText);
                setFeedback(`已复制：${copiedText}`, 'success');
            }
        );

        copyButton.setAttribute('aria-label', `复制标识：${item.identifier}`);

        const openButton = createButton(
            'work-item__open',
            '↗',
            `打开地址：${item.displayUrl}`,
            () => {
                window.open(item.openUrl, '_blank', 'noopener,noreferrer');
            }
        );

        openButton.setAttribute('aria-label', `打开地址：${item.displayUrl}`);

        const meta = document.createElement('div');
        meta.className = 'work-item__meta';

        const hostLine = createMetaLine('站点', `${item.siteInfo.host}${item.siteInfo.path}`);
        const codeLine = createMetaLine('结果', buildSiteSummaryText(item.siteInfo));
        const sourceLine = createMetaLine('来源', item.siteInfo.sourceText || '未识别');
        const expireLine = createMetaLine('到期', item.siteInfo.expiresAt || '未提供');
        const timeLine = createMetaLine('刷新', formatCheckedAt(item.siteInfo.checkedAt));
        meta.append(hostLine, codeLine, sourceLine, expireLine, timeLine);
        itemCard.append(copyButton, openButton, meta);
        itemsGrid.appendChild(itemCard);
    });
}

async function importCurrentTextarea() {
    const content = batchContentInput.value.trim();
    if (!content) {
        setFeedback('请先粘贴内容或导入 txt 文件。', 'warning');
        return;
    }

    const parseResult = parseBatchContent(content);
    currentInvalidLines = parseResult.invalidLines;

    if (!parseResult.items.length) {
        currentItems = Object.freeze([]);
        currentSavedAt = '';
        renderItems();
        setFeedback('没有解析出有效数据，请检查分隔符和地址格式。', 'error');
        return;
    }

    persistLocalState(parseResult.items);
    renderItems();

    const successMessage = parseResult.invalidLines.length
        ? `已保存 ${parseResult.items.length} 条有效数据，另有 ${parseResult.invalidLines.length} 行未导入。`
        : `已保存 ${parseResult.items.length} 条数据到浏览器本地。`;

    setFeedback(successMessage, parseResult.invalidLines.length ? 'warning' : 'success');
}

async function handleFileImport(file) {
    if (!file) {
        return;
    }

    const textContent = await file.text();
    batchContentInput.value = textContent;
    setFeedback(`已读取文件：${file.name}，请确认后点击“解析并保存到本地”。`, 'success');
}

function isReadableContentType(contentType) {
    const normalizedContentType = String(contentType || '').toLowerCase();
    return (
        normalizedContentType.includes('text/') ||
        normalizedContentType.includes('json') ||
        normalizedContentType.includes('html') ||
        !normalizedContentType
    );
}

async function fetchPageContentDirect(openUrl) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);

    try {
        const response = await fetch(openUrl, {
            method: 'GET',
            mode: 'cors',
            cache: 'no-store',
            signal: controller.signal,
            headers: {
                Accept: 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
            },
        });
        const contentType = response.headers.get('content-type') || '';
        const rawText = isReadableContentType(contentType) ? await response.text() : '';

        return {
            ok: response.ok,
            status: response.status,
            contentType,
            rawText,
        };
    } finally {
        window.clearTimeout(timeoutId);
    }
}

async function fetchPageContentViaServer(openUrl) {
    const response = await fetch('/local-tools/fetch-page', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url: openUrl }),
    });

    if (!response.ok) {
        throw new Error('proxy-fetch-failed');
    }

    const payload = await response.json();
    return {
        ok: Boolean(payload.success),
        status: payload.status_code || 0,
        contentType: payload.content_type || '',
        rawText: payload.text || '',
    };
}

async function fetchPageContent(openUrl) {
    try {
        return await fetchPageContentDirect(openUrl);
    } catch (_directError) {
        return await fetchPageContentViaServer(openUrl);
    }
}

async function fetchSiteInfoForItem(item) {
    const checkedAt = new Date().toISOString();
    const fallbackInfo = buildSiteInfo(item.openUrl, {
        ...item.siteInfo,
        checkedAt,
        statusText: '已刷新，显示网址信息',
    });

    try {
        const pageContent = await fetchPageContent(item.openUrl);

        if (!pageContent.ok) {
            return buildSiteInfo(item.openUrl, {
                ...fallbackInfo,
                statusText: `HTTP ${pageContent.status}`,
                checkedAt,
            });
        }

        const contentType = pageContent.contentType || '';
        if (isReadableContentType(contentType)) {
            const readableContent = extractReadablePageContent(pageContent.rawText, contentType);
            const verificationInfo = parseVerificationContent(readableContent.text);

            if (verificationInfo.codeText || verificationInfo.expiresAt || verificationInfo.sourceText) {
                return buildSiteInfo(item.openUrl, {
                    ...fallbackInfo,
                    title: readableContent.title,
                    codeText: verificationInfo.codeText,
                    sourceText: verificationInfo.sourceText,
                    expiresAt: verificationInfo.expiresAt,
                    statusText: verificationInfo.statusText || '已刷新，显示网址信息',
                    checkedAt,
                });
            }

            if (readableContent.title) {
                return buildSiteInfo(item.openUrl, {
                    ...fallbackInfo,
                    title: readableContent.title,
                    codeText: '',
                    sourceText: '',
                    expiresAt: '',
                    statusText: '已读取页面标题',
                    checkedAt,
                });
            }
        }

        const shortType = contentType.split(';')[0] || '可访问';
        return buildSiteInfo(item.openUrl, {
            ...fallbackInfo,
            codeText: '',
            sourceText: '',
            expiresAt: '',
            statusText: `已访问：${shortType}`,
            checkedAt,
        });
    } catch (error) {
        const isTimeout = error?.name === 'AbortError';
        return buildSiteInfo(item.openUrl, {
            ...fallbackInfo,
            codeText: '',
            sourceText: '',
            expiresAt: '',
            statusText: isTimeout ? '刷新超时，显示网址信息' : '站点限制读取，显示网址信息',
            checkedAt,
        });
    }
}

async function refreshAllSiteInfo() {
    if (!currentItems.length) {
        setFeedback('当前没有可刷新的数据。', 'warning');
        return;
    }

    setRefreshButtonState('刷新中 0/' + currentItems.length, true);

    let cursor = 0;
    let completed = 0;
    const refreshedItems = new Array(currentItems.length);

    const worker = async () => {
        while (cursor < currentItems.length) {
            const index = cursor;
            cursor += 1;
            const item = currentItems[index];
            const nextSiteInfo = await fetchSiteInfoForItem(item);
            refreshedItems[index] = Object.freeze({
                ...item,
                siteInfo: nextSiteInfo,
            });
            completed += 1;
            setRefreshButtonState(`刷新中 ${completed}/${currentItems.length}`, true);
        }
    };

    const workers = Array.from(
        { length: Math.min(REFRESH_CONCURRENCY, currentItems.length) },
        () => worker()
    );

    await Promise.all(workers);

    const nextItems = createFrozenItems(refreshedItems);
    persistLocalState(nextItems);
    renderItems();
    setRefreshButtonState('刷新全部信息', false);
    setFeedback(`已刷新 ${nextItems.length} 条站点信息。`, 'success');
}

importLocalToolsBtn.addEventListener('click', importCurrentTextarea);

clearTextareaBtn.addEventListener('click', () => {
    batchContentInput.value = '';
    setFeedback('输入框已清空。', 'success');
});

clearLocalDataBtn.addEventListener('click', () => {
    clearLocalState();
    renderItems();
    setFeedback('浏览器本地数据已清空。', 'success');
});

if (refreshAllSiteInfoBtn) {
    refreshAllSiteInfoBtn.addEventListener('click', refreshAllSiteInfo);
}

fileInput.addEventListener('change', async (event) => {
    const [file] = event.target.files || [];
    await handleFileImport(file);
});

searchInput.addEventListener('input', renderItems);

loadLocalState();
renderItems();
setRefreshButtonState('刷新全部信息', false);
