const LOCAL_STORAGE_KEY = 'local_tools_items_v1';

const batchContentInput = document.getElementById('batchContentInput');
const importFeedback = document.getElementById('importFeedback');
const importLocalToolsBtn = document.getElementById('importLocalToolsBtn');
const clearTextareaBtn = document.getElementById('clearTextareaBtn');
const clearLocalDataBtn = document.getElementById('clearLocalDataBtn');
const fileInput = document.getElementById('localToolsFileInput');
const itemsGrid = document.getElementById('itemsGrid');
const emptyState = document.getElementById('emptyState');
const totalItemsValue = document.getElementById('totalItemsValue');
const visibleItemsValue = document.getElementById('visibleItemsValue');
const lastSavedAtValue = document.getElementById('lastSavedAtValue');
const searchInput = document.getElementById('localToolsSearchInput');
const copyAllIdentifiersBtn = document.getElementById('copyAllIdentifiersBtn');
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

function buildDisplayUrl(url) {
    try {
        const parsed = new URL(url);
        return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
    } catch (_error) {
        return '';
    }
}

function createFrozenItems(items) {
    return Object.freeze(items.map((item) => Object.freeze({
        identifier: item.identifier,
        openUrl: item.openUrl,
        displayUrl: item.displayUrl,
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
                typeof item?.openUrl === 'string' &&
                typeof item?.displayUrl === 'string'
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
            identifier: item.identifier,
            openUrl: item.openUrl,
            displayUrl: item.displayUrl,
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
                identifier,
                openUrl,
                displayUrl: buildDisplayUrl(openUrl),
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

function createActionButton(label, className, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn ${className}`;
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
}

function renderItems() {
    const keyword = (searchInput.value || '').trim().toLowerCase();
    const filteredItems = currentItems.filter((item) =>
        !keyword || item.identifier.toLowerCase().includes(keyword) || item.displayUrl.toLowerCase().includes(keyword)
    );

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

    filteredItems.forEach((item, index) => {
        const itemCard = document.createElement('article');
        itemCard.className = 'item-card';

        const header = document.createElement('div');
        header.className = 'item-card__header';

        const indexBadge = document.createElement('span');
        indexBadge.className = 'item-card__index';
        indexBadge.textContent = String(index + 1);

        const identifier = document.createElement('div');
        identifier.className = 'item-card__identifier';
        identifier.textContent = item.identifier;

        header.append(indexBadge, identifier);

        const meta = document.createElement('p');
        meta.className = 'item-card__meta';
        meta.textContent = '展示地址已隐藏查询参数；打开时仍会使用完整地址。';

        const displayUrl = document.createElement('div');
        displayUrl.className = 'item-card__display-url';
        displayUrl.textContent = item.displayUrl;

        const actions = document.createElement('div');
        actions.className = 'item-card__actions';
        actions.append(
            createActionButton('复制标识', 'btn-secondary', async () => {
                await copyText(item.identifier);
                setFeedback(`已复制：${item.identifier}`, 'success');
            }),
            createActionButton('打开地址', 'btn-primary', () => {
                window.open(item.openUrl, '_blank', 'noopener,noreferrer');
            })
        );

        itemCard.append(header, meta, displayUrl, actions);
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

fileInput.addEventListener('change', async (event) => {
    const [file] = event.target.files || [];
    await handleFileImport(file);
});

searchInput.addEventListener('input', renderItems);

copyAllIdentifiersBtn.addEventListener('click', async () => {
    if (!currentItems.length) {
        setFeedback('当前没有可复制的数据。', 'warning');
        return;
    }

    await copyText(currentItems.map((item) => item.identifier).join('\n'));
    setFeedback(`已复制 ${currentItems.length} 条标识。`, 'success');
});

loadLocalState();
renderItems();
