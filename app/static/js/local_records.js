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

function formatCardExpiry(value) {
    const normalizedValue = normalizeText(value);
    if (!normalizedValue) {
        return '';
    }

    const yearMonthMatch = normalizedValue.match(/^(\d{4})\s*[\/.-]\s*(\d{1,2})$/);
    const monthYearMatch = normalizedValue.match(/^(\d{1,2})\s*[\/.-]\s*(\d{2}|\d{4})$/);
    const matchedParts = (() => {
        if (yearMonthMatch) {
            return { month: yearMonthMatch[2], year: yearMonthMatch[1] };
        }

        if (monthYearMatch) {
            return { month: monthYearMatch[1], year: monthYearMatch[2] };
        }

        return null;
    })();

    if (!matchedParts) {
        return '';
    }

    const month = Number(matchedParts.month);
    if (!Number.isInteger(month) || month < 1 || month > 12) {
        return '';
    }

    return `${String(month).padStart(2, '0')}/${String(matchedParts.year).slice(-2).padStart(2, '0')}`;
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
    return Object.freeze(records.map((record, index) => {
        const cardNumber = digitsOnly(record.cardNumber || record.cardFull || '');
        const cardExpiry = formatCardExpiry(record.cardExpiry || record.expiry || record.expiration || '');
        const phone = normalizeText(record.phone || record.phoneFull || '');
        const rawText = normalizeText(record.rawText || '');
        const extraCode = normalizeText(record.extraCode || '');

        return Object.freeze({
            id: String(record.id || `${Date.now()}-${index + 1}`),
            sequence: Number.isInteger(record.sequence) ? record.sequence : index + 1,
            name: normalizeText(record.name),
            address: normalizeText(record.address),
            rawText,
            note: redactSensitiveText(record.note || ''),
            cardNumber,
            cardMasked: normalizeText(record.cardMasked),
            cardLast4: digitsOnly(record.cardLast4 || cardNumber).slice(-4),
            cardExpiry,
            extraCode,
            phone,
            phoneMasked: normalizeText(record.phoneMasked),
            importedAt: String(record.importedAt || ''),
            warnings: Object.freeze(Array.isArray(record.warnings) ? record.warnings.map(normalizeText).filter(Boolean) : []),
        });
    }));
}

function buildRecord(values) {
    return Object.freeze({
        id: `${Date.now()}-${values.sequence}`,
        sequence: values.sequence,
        name: normalizeText(values.name),
        address: normalizeText(values.address),
        rawText: normalizeText(values.rawText),
        note: redactSensitiveText(values.note || ''),
        cardNumber: digitsOnly(values.cardNumber || ''),
        cardMasked: normalizeText(values.cardMasked),
        cardLast4: digitsOnly(values.cardLast4 || '').slice(-4),
        cardExpiry: formatCardExpiry(values.cardExpiry || ''),
        extraCode: normalizeText(values.extraCode),
        phone: normalizeText(values.phone),
        phoneMasked: normalizeText(values.phoneMasked),
        importedAt: new Date().toISOString(),
        warnings: Object.freeze((values.warnings || []).map(normalizeText).filter(Boolean)),
    });
}

function parsePlainTextRecord(line, sequence) {
    const rawText = normalizeText(line);
    if (!rawText) {
        return { error: '内容为空' };
    }

    return {
        record: buildRecord({
            sequence,
            rawText,
        }),
        skippedSensitive: 0,
    };
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
    const cardExpiry = formatCardExpiry(parts[1]);
    const extraCode = hasSecretUrl(parts[2]) || isLikelyCardNumber(parts[2])
        ? ''
        : normalizeText(parts[2]);
    const phone = normalizeText(parts[3]);
    const skippedLabels = [
        hasSecretUrl(parts.slice(0, -2).join(' ')) ? '短信 API Key/接口地址' : '',
    ].filter(Boolean);
    const warnings = [
        skippedLabels.length ? `已忽略：${skippedLabels.join('、')}` : '',
        parts[1] && !cardExpiry ? '有效期格式未识别，已跳过。' : '',
    ].filter(Boolean);

    return {
        record: buildRecord({
            sequence,
            name,
            address,
            cardNumber: cardDigits,
            cardMasked: maskCard(parts[0]),
            cardLast4: cardDigits.slice(-4),
            cardExpiry,
            extraCode,
            phone,
            phoneMasked: maskPhone(phone),
            note: skippedLabels.length ? '短信接口等敏感字段已在导入时丢弃。' : '',
            warnings,
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
    const rawLine = String(line || '').trim();
    const parts = line.split(/\s*-{4,}\s*/).map(normalizeText).filter(Boolean);
    if (parts.length < 2) {
        if (isLikelyCardNumber(rawLine) || hasSecretUrl(rawLine)) {
            return { error: '缺少有效分隔符 ----' };
        }

        return parsePlainTextRecord(rawLine, sequence);
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
        currentRecords = createFrozenRecords(parsedRecords.filter((record) => {
            const hasStructuredFields = typeof record?.name === 'string' && typeof record?.address === 'string';
            const hasPlainTextField = typeof record?.rawText === 'string';
            return hasStructuredFields || hasPlainTextField;
        }));
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
            rawText: record.rawText,
            note: record.note,
            cardNumber: record.cardNumber,
            cardMasked: record.cardMasked,
            cardLast4: record.cardLast4,
            cardExpiry: record.cardExpiry,
            extraCode: record.extraCode,
            phone: record.phone,
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
    const safeText = String(text || '');
    if (!safeText) {
        return false;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(safeText);
            return true;
        } catch (_error) {
            // 部分本地浏览器环境会拒绝 Clipboard API，继续使用兼容方案。
        }
    }

    const tempInput = document.createElement('textarea');
    tempInput.value = safeText;
    tempInput.setAttribute('readonly', 'readonly');
    tempInput.style.position = 'absolute';
    tempInput.style.left = '-9999px';
    tempInput.style.top = '0';
    document.body.appendChild(tempInput);
    tempInput.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(tempInput);
    return copied;
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
        record.rawText,
        record.note,
        record.cardNumber,
        record.cardMasked,
        record.cardLast4,
        record.cardExpiry,
        record.extraCode,
        record.phone,
        record.phoneMasked,
        record.warnings.join(' '),
    ].join(' ').toLowerCase();
}

function createCopyValueButton(label, displayValue, copyValue = displayValue) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'record-card__copy-value';
    button.textContent = displayValue;
    button.title = `点击复制${label}`;
    button.setAttribute('aria-label', `点击复制${label}：${displayValue}`);
    button.dataset.copyValue = copyValue;
    button.addEventListener('click', async () => {
        const copied = await copyText(copyValue);
        setRecordFeedback(copied ? `已复制${label}。` : `复制${label}失败，请手动选择字段内容。`, copied ? 'success' : 'error');
    });
    return button;
}

function createCopyField(label, displayValue, copyValue = displayValue) {
    const line = document.createElement('div');
    line.className = 'record-card__field';

    const strong = document.createElement('strong');
    strong.textContent = `${label}：`;

    const safeDisplayValue = normalizeText(displayValue);
    const safeCopyValue = typeof copyValue === 'string' ? copyValue.trim() : safeDisplayValue;
    const valueElement = safeDisplayValue
        ? createCopyValueButton(label, safeDisplayValue, safeCopyValue || safeDisplayValue)
        : document.createElement('span');

    if (!safeDisplayValue) {
        valueElement.className = 'record-card__empty-value';
        valueElement.textContent = '未保存';
    }

    line.append(strong, valueElement);
    return line;
}

function renderRecordCard(record) {
    const card = document.createElement('article');
    card.className = 'record-card';

    const head = document.createElement('div');
    head.className = 'record-card__head';
    const title = document.createElement('h3');
    title.className = 'record-card__title';
    if (record.rawText) {
        title.textContent = '纯文本';
    } else {
        title.appendChild(createCopyValueButton('姓名', record.name));
    }
    const badge = document.createElement('span');
    badge.className = 'record-card__badge';
    badge.textContent = `#${record.sequence}`;
    head.append(title, badge);

    const cardDisplayValue = record.cardNumber || record.cardMasked || (record.cardLast4 ? `尾号 ${record.cardLast4}` : '');
    const phoneDisplayValue = record.phone || record.phoneMasked;
    const fields = document.createElement('div');
    fields.className = 'record-card__fields';
    if (record.rawText) {
        fields.append(createCopyField('内容', record.rawText));
    } else {
        fields.append(
            createCopyField('地址', record.address),
            createCopyField('卡号', cardDisplayValue, record.cardNumber || record.cardLast4 || cardDisplayValue),
            createCopyField('有效期', record.cardExpiry),
            createCopyField('附加字段', record.extraCode),
            createCopyField('电话', phoneDisplayValue),
            createCopyField('备注', record.note)
        );
    }

    card.append(head, fields);
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
