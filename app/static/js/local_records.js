const RECORD_STORAGE_KEY = 'local_record_workbench_items_v1';

const recordBatchInput = document.getElementById('recordBatchInput');
const recordFeedback = document.getElementById('recordFeedback');
const importRecordWorkbenchBtn = document.getElementById('importRecordWorkbenchBtn');
const clearRecordTextareaBtn = document.getElementById('clearRecordTextareaBtn');
const clearRecordLocalDataBtn = document.getElementById('clearRecordLocalDataBtn');
const recordFileInput = document.getElementById('recordFileInput');
const recordItemsGrid = document.getElementById('recordItemsGrid');
const recordEmptyState = document.getElementById('recordEmptyState');
const recordTotalValue = document.getElementById('recordTotalValue');
const recordVisibleValue = document.getElementById('recordVisibleValue');
const recordSavedAtValue = document.getElementById('recordSavedAtValue');
const recordSearchInput = document.getElementById('recordSearchInput');
const recordInvalidLinesBox = document.getElementById('recordInvalidLinesBox');
const recordInvalidLinesList = document.getElementById('recordInvalidLinesList');

let currentRecords = Object.freeze([]);
let currentInvalidLines = Object.freeze([]);
let currentSavedAt = '';

function setRecordFeedback(message, tone = '') {
    recordFeedback.textContent = message;
    recordFeedback.className = 'feedback';
    if (tone) {
        recordFeedback.classList.add(`feedback--${tone}`);
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

function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function digitsOnly(value) {
    return String(value || '').replace(/\D/g, '');
}

function isLikelyCardNumber(value) {
    const digits = digitsOnly(value);
    return digits.length >= 13 && digits.length <= 19;
}

function hasSecretUrl(value) {
    return /https?:\/\/\S+/i.test(String(value || '')) && /(?:[?&](?:key|token|api_key)=|\/api\/)/i.test(String(value || ''));
}

function hasCvvLikeValue(value) {
    return /^\d{3,4}$/.test(String(value || '').trim());
}

function maskCard(value) {
    const digits = digitsOnly(value);
    if (!isLikelyCardNumber(digits)) {
        return '';
    }

    return `•••• ${digits.slice(-4)}`;
}

function maskPhone(value) {
    const rawValue = String(value || '').trim();
    const digits = digitsOnly(rawValue);
    if (digits.length < 7) {
        return '';
    }

    const prefix = rawValue.startsWith('+') ? '+' : '';
    return `${prefix}••••${digits.slice(-4)}`;
}

function redactSensitiveText(value) {
    return normalizeText(value)
        .replace(/\b(?:\d[ -]?){13,19}\b/g, '[已移除卡号]')
        .replace(/https?:\/\/\S*(?:[?&](?:key|token|api_key)=|\/api\/)\S*/ig, '[已移除接口地址]')
        .replace(/\b(?:cvv|cvc|security\s*code)\b\s*[:：=]?\s*\d{3,4}\b/ig, '[已移除安全码]');
}

function createFrozenRecords(records) {
    return Object.freeze(records.map((record, index) => Object.freeze({
        id: String(record.id || `${Date.now()}-${index + 1}`),
        sequence: Number.isInteger(record.sequence) ? record.sequence : index + 1,
        name: normalizeText(record.name),
        address: normalizeText(record.address),
        note: redactSensitiveText(record.note || ''),
        cardMasked: normalizeText(record.cardMasked),
        cardLast4: digitsOnly(record.cardLast4 || '').slice(-4),
        phoneMasked: normalizeText(record.phoneMasked),
        importedAt: String(record.importedAt || ''),
        warnings: Object.freeze(Array.isArray(record.warnings) ? record.warnings.map(normalizeText).filter(Boolean) : []),
    })));
}

function buildRecord(values) {
    return Object.freeze({
        id: `${Date.now()}-${values.sequence}`,
        sequence: values.sequence,
        name: normalizeText(values.name),
        address: normalizeText(values.address),
        note: redactSensitiveText(values.note || ''),
        cardMasked: normalizeText(values.cardMasked),
        cardLast4: digitsOnly(values.cardLast4 || '').slice(-4),
        phoneMasked: normalizeText(values.phoneMasked),
        importedAt: new Date().toISOString(),
        warnings: Object.freeze((values.warnings || []).map(normalizeText).filter(Boolean)),
    });
}

function validateNameAddress(name, address) {
    if (!name) {
        return '姓名为空';
    }

    if (!address) {
        return '地址为空';
    }

    return '';
}

function parsePaymentStyleRecord(parts, sequence) {
    if (parts.length < 7) {
        return { error: '包含卡号但缺少姓名或地址字段' };
    }

    const name = normalizeText(parts[parts.length - 2]);
    const address = normalizeText(parts[parts.length - 1]);
    const validationError = validateNameAddress(name, address);
    if (validationError) {
        return { error: validationError };
    }

    const cardDigits = digitsOnly(parts[0]);
    const skippedLabels = [
        isLikelyCardNumber(parts[0]) ? '完整卡号' : '',
        parts[1] ? '到期日' : '',
        hasCvvLikeValue(parts[2]) ? 'CVV' : '',
        hasSecretUrl(parts.slice(0, -2).join(' ')) ? '短信 API Key/接口地址' : '',
    ].filter(Boolean);

    return {
        record: buildRecord({
            sequence,
            name,
            address,
            cardMasked: maskCard(parts[0]),
            cardLast4: cardDigits.slice(-4),
            phoneMasked: maskPhone(parts[3]),
            note: '敏感字段已在导入时丢弃。',
            warnings: skippedLabels.length
                ? [`已忽略：${skippedLabels.join('、')}`]
                : ['已按敏感格式导入，仅保留可用摘要。'],
        }),
        skippedSensitive: skippedLabels.length,
    };
}

function parseGenericRecord(parts, sequence) {
    const name = normalizeText(parts[0]);
    const address = normalizeText(parts[1]);
    const validationError = validateNameAddress(name, address);
    if (validationError) {
        return { error: validationError };
    }

    const extraText = parts.slice(2).join(' / ');
    const hasRedactedExtra = isLikelyCardNumber(extraText) || hasSecretUrl(extraText);

    return {
        record: buildRecord({
            sequence,
            name,
            address,
            note: redactSensitiveText(extraText),
            warnings: hasRedactedExtra ? ['备注中疑似敏感内容已移除。'] : [],
        }),
        skippedSensitive: hasRedactedExtra ? 1 : 0,
    };
}

function parseRecordLine(line, sequence) {
    const parts = line.split(/\s*-{4,}\s*/).map(normalizeText).filter(Boolean);
    if (parts.length < 2) {
        return { error: '缺少有效分隔符 ----' };
    }

    if (isLikelyCardNumber(parts[0]) || hasSecretUrl(parts.join(' '))) {
        return parsePaymentStyleRecord(parts, sequence);
    }

    return parseGenericRecord(parts, sequence);
}

function parseRecordBatch(content) {
    const lines = String(content || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);

    const parsed = lines.reduce((result, line, index) => {
        const parsedLine = parseRecordLine(line, result.records.length + 1);
        if (parsedLine.error) {
            return Object.freeze({
                records: result.records,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: parsedLine.error }]),
                skippedSensitive: result.skippedSensitive,
            });
        }

        return Object.freeze({
            records: result.records.concat([parsedLine.record]),
            invalidLines: result.invalidLines,
            skippedSensitive: result.skippedSensitive + (parsedLine.skippedSensitive || 0),
        });
    }, Object.freeze({ records: [], invalidLines: [], skippedSensitive: 0 }));

    return Object.freeze({
        records: createFrozenRecords(parsed.records),
        invalidLines: Object.freeze(parsed.invalidLines.map((item) => Object.freeze(item))),
        skippedSensitive: parsed.skippedSensitive,
    });
}

function loadRecordState() {
    try {
        const rawValue = window.localStorage.getItem(RECORD_STORAGE_KEY);
        if (!rawValue) {
            return;
        }

        const parsedValue = JSON.parse(rawValue);
        const parsedRecords = Array.isArray(parsedValue?.records) ? parsedValue.records : [];
        currentRecords = createFrozenRecords(parsedRecords.filter((record) =>
            typeof record?.name === 'string' && typeof record?.address === 'string'
        ));
        currentSavedAt = typeof parsedValue?.savedAt === 'string' ? parsedValue.savedAt : '';
        currentInvalidLines = Object.freeze([]);
    } catch (_error) {
        currentRecords = Object.freeze([]);
        currentSavedAt = '';
        currentInvalidLines = Object.freeze([]);
        setRecordFeedback('读取本地记录失败，已忽略旧数据。', 'warning');
    }
}

function persistRecordState(records) {
    const savedAt = new Date().toISOString();
    const storagePayload = {
        savedAt,
        records: records.map((record) => ({
            id: record.id,
            sequence: record.sequence,
            name: record.name,
            address: record.address,
            note: record.note,
            cardMasked: record.cardMasked,
            cardLast4: record.cardLast4,
            phoneMasked: record.phoneMasked,
            importedAt: record.importedAt,
            warnings: record.warnings,
        })),
    };

    window.localStorage.setItem(RECORD_STORAGE_KEY, JSON.stringify(storagePayload));
    currentRecords = createFrozenRecords(records);
    currentSavedAt = savedAt;
}

function clearRecordState() {
    window.localStorage.removeItem(RECORD_STORAGE_KEY);
    currentRecords = Object.freeze([]);
    currentInvalidLines = Object.freeze([]);
    currentSavedAt = '';
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

function renderRecordInvalidLines(invalidLines) {
    recordInvalidLinesList.innerHTML = '';

    if (!invalidLines.length) {
        recordInvalidLinesBox.hidden = true;
        return;
    }

    invalidLines.forEach((item) => {
        const line = document.createElement('li');
        line.textContent = `第 ${item.lineNumber} 行：${item.reason}`;
        recordInvalidLinesList.appendChild(line);
    });

    recordInvalidLinesBox.hidden = false;
}

function buildSearchableRecordText(record) {
    return [
        record.name,
        record.address,
        record.note,
        record.cardMasked,
        record.cardLast4,
        record.phoneMasked,
        record.warnings.join(' '),
    ].join(' ').toLowerCase();
}

function createRecordButton(text, className, title, onClick, disabled = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = text;
    button.title = title;
    button.disabled = disabled;
    button.addEventListener('click', onClick);
    return button;
}

function createMetaLine(label, value) {
    const line = document.createElement('div');
    line.className = 'record-card__meta-line';

    const strong = document.createElement('strong');
    strong.textContent = `${label}：`;

    const span = document.createElement('span');
    span.textContent = value || '未提供';

    line.append(strong, span);
    return line;
}

function renderRecordCard(record) {
    const card = document.createElement('article');
    card.className = 'record-card';

    const head = document.createElement('div');
    head.className = 'record-card__head';
    const title = document.createElement('h3');
    title.className = 'record-card__title';
    title.textContent = record.name;
    const badge = document.createElement('span');
    badge.className = 'record-card__badge';
    badge.textContent = `#${record.sequence}`;
    head.append(title, badge);

    const address = document.createElement('p');
    address.className = 'record-card__address';
    address.textContent = record.address;

    const actions = document.createElement('div');
    actions.className = 'record-card__actions';
    actions.append(
        createRecordButton('复制姓名', 'record-card__button record-card__button--primary', `复制姓名：${record.name}`, async () => {
            await copyText(record.name);
            setRecordFeedback(`已复制姓名：${record.name}`, 'success');
        }),
        createRecordButton('复制地址', 'record-card__button', `复制地址：${record.address}`, async () => {
            await copyText(record.address);
            setRecordFeedback('已复制地址。', 'success');
        }),
        createRecordButton('复制姓名+地址', 'record-card__button', '复制姓名和地址', async () => {
            await copyText(`${record.name}\n${record.address}`);
            setRecordFeedback('已复制姓名和地址。', 'success');
        }),
        createRecordButton(
            record.cardLast4 ? '复制卡尾号' : '无卡尾号',
            'record-card__button record-card__button--muted',
            record.cardLast4 ? `复制卡尾号：${record.cardLast4}` : '没有可复制的脱敏卡尾号',
            async () => {
                await copyText(record.cardLast4);
                setRecordFeedback(`已复制卡尾号：${record.cardLast4}`, 'success');
            },
            !record.cardLast4
        )
    );

    const meta = document.createElement('div');
    meta.className = 'record-card__meta';
    meta.append(
        createMetaLine('卡号', record.cardMasked || '未保存'),
        createMetaLine('电话', record.phoneMasked || '未保存'),
        createMetaLine('备注', record.note || '无')
    );

    card.append(head, address, actions, meta);
    if (record.warnings.length) {
        const warning = document.createElement('p');
        warning.className = 'record-card__warning';
        warning.textContent = record.warnings.join('；');
        card.appendChild(warning);
    }

    return card;
}

function renderRecords() {
    const keyword = (recordSearchInput.value || '').trim().toLowerCase();
    const filteredRecords = currentRecords.filter((record) => (
        !keyword || buildSearchableRecordText(record).includes(keyword)
    ));

    recordItemsGrid.innerHTML = '';
    recordTotalValue.textContent = String(currentRecords.length);
    recordVisibleValue.textContent = String(filteredRecords.length);
    recordSavedAtValue.textContent = formatSavedAt(currentSavedAt);
    renderRecordInvalidLines(currentInvalidLines);

    if (!currentRecords.length) {
        recordEmptyState.hidden = false;
        recordItemsGrid.hidden = true;
        return;
    }

    recordEmptyState.hidden = true;
    recordItemsGrid.hidden = false;
    filteredRecords.forEach((record) => {
        recordItemsGrid.appendChild(renderRecordCard(record));
    });
}

async function importCurrentRecords() {
    const content = recordBatchInput.value.trim();
    if (!content) {
        setRecordFeedback('请先粘贴内容或导入 txt 文件。', 'warning');
        return;
    }

    const parseResult = parseRecordBatch(content);
    currentInvalidLines = parseResult.invalidLines;

    if (!parseResult.records.length) {
        currentRecords = Object.freeze([]);
        currentSavedAt = '';
        renderRecords();
        setRecordFeedback('没有解析出有效记录，请检查分隔符和字段顺序。', 'error');
        return;
    }

    persistRecordState(parseResult.records);
    if (parseResult.skippedSensitive > 0) {
        recordBatchInput.value = '';
    }
    renderRecords();

    const skippedText = parseResult.skippedSensitive > 0 ? `，已丢弃 ${parseResult.skippedSensitive} 类敏感字段并清空输入框` : '';
    const invalidText = parseResult.invalidLines.length ? `，另有 ${parseResult.invalidLines.length} 行未导入` : '';
    setRecordFeedback(`已保存 ${parseResult.records.length} 条本地记录${skippedText}${invalidText}。`, parseResult.invalidLines.length ? 'warning' : 'success');
}

async function handleRecordFileImport(file) {
    if (!file) {
        return;
    }

    const textContent = await file.text();
    recordBatchInput.value = textContent;
    setRecordFeedback(`已读取文件：${file.name}，请确认后点击“解析并保存到本地”。`, 'success');
}

importRecordWorkbenchBtn.addEventListener('click', importCurrentRecords);

clearRecordTextareaBtn.addEventListener('click', () => {
    recordBatchInput.value = '';
    setRecordFeedback('输入框已清空。', 'success');
});

clearRecordLocalDataBtn.addEventListener('click', () => {
    clearRecordState();
    renderRecords();
    setRecordFeedback('浏览器本地记录已清空。', 'success');
});

recordFileInput.addEventListener('change', async (event) => {
    const [file] = event.target.files || [];
    await handleRecordFileImport(file);
});

recordSearchInput.addEventListener('input', renderRecords);

loadRecordState();
renderRecords();
