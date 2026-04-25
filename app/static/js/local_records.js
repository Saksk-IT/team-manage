const RECORD_STORAGE_KEY = 'local_record_workbench_items_v1';
const RECORD_REFRESH_TIMEOUT_MS = 6000;

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

function extractTitleFromHtml(html) {
    const match = String(html || '').match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    return match ? match[1].replace(/\s+/g, ' ').trim() : '';
}

function extractReadablePageContent(rawText, contentType) {
    const normalizedContentType = String(contentType || '').toLowerCase();

    if (normalizedContentType.includes('text/html')) {
        try {
            const parser = new DOMParser();
            const doc = parser.parseFromString(String(rawText || ''), 'text/html');
            return Object.freeze({
                title: normalizeReadableText(doc.title),
                text: normalizeReadableText(doc.body?.textContent || ''),
            });
        } catch (_error) {
            return Object.freeze({
                title: extractTitleFromHtml(rawText),
                text: normalizeReadableText(rawText),
            });
        }
    }

    return Object.freeze({
        title: '',
        text: normalizeReadableText(rawText),
    });
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
    const bracketSegment = pipeSegments.find((segment) => /^\(.+\)$/.test(segment));
    const fallbackSourceMatch = normalizedText.match(/\(([^()]{1,80})\)/);
    const sourceText = bracketSegment
        ? bracketSegment.replace(/^\(|\)$/g, '').trim()
        : (fallbackSourceMatch ? fallbackSourceMatch[1].trim() : '');

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

function createFrozenToolItem(toolItem, sequence) {
    if (!toolItem || typeof toolItem !== 'object') {
        return null;
    }

    const identifier = normalizeText(toolItem.identifier);
    const openUrl = String(toolItem.openUrl || '').trim();
    if (!identifier || !openUrl) {
        return null;
    }

    return Object.freeze({
        sequence: Number.isInteger(toolItem.sequence) ? toolItem.sequence : sequence,
        identifier,
        openUrl,
        displayUrl: normalizeText(toolItem.displayUrl || buildDisplayUrl(openUrl)),
        siteInfo: buildSiteInfo(openUrl, toolItem.siteInfo || {}),
    });
}

function createFrozenRecords(records) {
    return Object.freeze(records.map((record, index) => {
        const cardNumber = digitsOnly(record.cardNumber || record.cardFull || '');
        const cardExpiry = formatCardExpiry(record.cardExpiry || record.expiry || record.expiration || '');
        const phone = normalizeText(record.phone || record.phoneFull || '');
        const rawText = normalizeText(record.rawText || '');
        const extraCode = normalizeText(record.extraCode || '');
        const sequence = Number.isInteger(record.sequence) ? record.sequence : index + 1;
        const toolItem = createFrozenToolItem(record.toolItem || record.localToolItem, sequence);

        return Object.freeze({
            id: String(record.id || `${Date.now()}-${index + 1}`),
            sequence,
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
            toolItem,
        });
    }));
}

function buildRecord(values) {
    const sequence = Number.isInteger(values.sequence) ? values.sequence : 1;
    return Object.freeze({
        id: `${Date.now()}-${sequence}`,
        sequence,
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
        toolItem: createFrozenToolItem(values.toolItem, sequence),
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

function splitInlinePaymentPrefix(value) {
    const tokens = normalizeText(value).split(/\s+/).filter(Boolean);
    if (tokens.length < 2) {
        return null;
    }

    const cardCandidate = tokens[tokens.length - 1];
    const ignoredPrefix = normalizeText(tokens.slice(0, -1).join(' '));
    if (!ignoredPrefix || !isLikelyCardNumber(cardCandidate)) {
        return null;
    }

    return Object.freeze({
        cardPart: cardCandidate,
        ignoredPrefix,
    });
}

function normalizePaymentStyleParts(parts) {
    if (
        parts.length >= 8 &&
        !isLikelyCardNumber(parts[0]) &&
        !hasSecretUrl(parts[0]) &&
        isLikelyCardNumber(parts[1]) &&
        formatCardExpiry(parts[2])
    ) {
        return Object.freeze({
            parts: Object.freeze(parts.slice(1)),
            ignoredPrefix: normalizeText(parts[0]),
        });
    }

    const inlinePrefix = splitInlinePaymentPrefix(parts[0]);
    if (
        parts.length >= 7 &&
        inlinePrefix &&
        formatCardExpiry(parts[1])
    ) {
        return Object.freeze({
            parts: Object.freeze([inlinePrefix.cardPart].concat(parts.slice(1))),
            ignoredPrefix: inlinePrefix.ignoredPrefix,
        });
    }

    return Object.freeze({
        parts: Object.freeze(parts),
        ignoredPrefix: '',
    });
}

function parsePaymentStyleRecord(parts, sequence, ignoredPrefix = '') {
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
    const hasSecretEndpoint = hasSecretUrl(parts.slice(0, -2).join(' '));
    const skippedLabels = [
        ignoredPrefix ? '无用前缀' : '',
        hasSecretEndpoint ? '短信 API Key/接口地址' : '',
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
            note: hasSecretEndpoint ? '短信接口等敏感字段已在导入时丢弃。' : '',
            warnings,
        }),
        skippedSensitive: hasSecretEndpoint ? 1 : 0,
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

function splitLocalToolLine(line) {
    const rawLine = String(line || '').trim();
    const pipeIndex = rawLine.indexOf('|');
    if (pipeIndex >= 0) {
        return Object.freeze({
            delimiter: 'pipe',
            identifier: rawLine.slice(0, pipeIndex).trim(),
            openUrl: rawLine.slice(pipeIndex + 1).trim(),
        });
    }

    const dashParts = rawLine.split(/\s*-{4,}\s*/);
    if (dashParts.length === 2) {
        return Object.freeze({
            delimiter: 'dash',
            identifier: (dashParts[0] || '').trim(),
            openUrl: (dashParts[1] || '').trim(),
        });
    }

    return null;
}

function isValidHttpUrl(value) {
    try {
        const parsedUrl = new URL(value);
        return ['http:', 'https:'].includes(parsedUrl.protocol);
    } catch (_error) {
        return false;
    }
}

function shouldParseAsLocalToolLine(line) {
    const localToolLine = splitLocalToolLine(line);
    if (!localToolLine) {
        return false;
    }

    if (localToolLine.delimiter === 'pipe') {
        return true;
    }

    return isValidHttpUrl(localToolLine.openUrl);
}

function buildLocalToolItem(values) {
    const sequence = Number.isInteger(values.sequence) ? values.sequence : 1;
    const openUrl = String(values.openUrl || '').trim();
    return Object.freeze({
        sequence,
        identifier: normalizeText(values.identifier),
        openUrl,
        displayUrl: buildDisplayUrl(openUrl),
        siteInfo: buildSiteInfo(openUrl),
    });
}

function parseLocalToolLine(line, sequence) {
    const localToolLine = splitLocalToolLine(line);
    if (!localToolLine) {
        return { error: '缺少有效分隔符 ---- 或 |' };
    }

    const identifier = normalizeText(localToolLine.identifier);
    if (!identifier) {
        return { error: '标识为空' };
    }

    if (!isValidHttpUrl(localToolLine.openUrl)) {
        return { error: '地址不是有效的 http/https URL' };
    }

    return {
        toolItem: buildLocalToolItem({
            sequence,
            identifier,
            openUrl: localToolLine.openUrl,
        }),
        skippedSensitive: 0,
    };
}

function combineRecordsAndToolItems(records, toolItems) {
    const maxCount = Math.max(records.length, toolItems.length);
    return Object.freeze(Array.from({ length: maxCount }, (_unused, index) => {
        const record = records[index];
        const toolItem = toolItems[index] || null;
        const sequence = index + 1;

        if (record) {
            return Object.freeze({
                ...record,
                sequence,
                toolItem,
            });
        }

        return buildRecord({
            sequence,
            toolItem,
        });
    }));
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

    const paymentStyle = normalizePaymentStyleParts(parts);
    if (isLikelyCardNumber(paymentStyle.parts[0]) || hasSecretUrl(paymentStyle.parts.join(' '))) {
        return parsePaymentStyleRecord(paymentStyle.parts, sequence, paymentStyle.ignoredPrefix);
    }

    return parseGenericRecord(parts, sequence);
}

function parseRecordBatch(content) {
    const lines = String(content || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);

    const parsed = lines.reduce((result, line, index) => {
        const parsedLine = shouldParseAsLocalToolLine(line)
            ? parseLocalToolLine(line, result.toolItems.length + 1)
            : parseRecordLine(line, result.records.length + 1);
        if (parsedLine.error) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: parsedLine.error }]),
                skippedSensitive: result.skippedSensitive,
            });
        }

        if (parsedLine.toolItem) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems.concat([parsedLine.toolItem]),
                invalidLines: result.invalidLines,
                skippedSensitive: result.skippedSensitive,
            });
        }

        return Object.freeze({
            records: result.records.concat([parsedLine.record]),
            toolItems: result.toolItems,
            invalidLines: result.invalidLines,
            skippedSensitive: result.skippedSensitive + (parsedLine.skippedSensitive || 0),
        });
    }, Object.freeze({ records: [], toolItems: [], invalidLines: [], skippedSensitive: 0 }));

    const combinedRecords = combineRecordsAndToolItems(parsed.records, parsed.toolItems);

    return Object.freeze({
        records: createFrozenRecords(combinedRecords),
        invalidLines: Object.freeze(parsed.invalidLines.map((item) => Object.freeze(item))),
        skippedSensitive: parsed.skippedSensitive,
        recordCount: parsed.records.length,
        toolItemCount: parsed.toolItems.length,
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
            const hasToolItem = typeof record?.toolItem?.identifier === 'string' && typeof record?.toolItem?.openUrl === 'string';
            return hasStructuredFields || hasPlainTextField || hasToolItem;
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
            toolItem: record.toolItem,
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

function buildSearchableToolText(toolItem) {
    if (!toolItem) {
        return '';
    }

    return [
        toolItem.identifier,
        toolItem.displayUrl,
        toolItem.openUrl,
        toolItem.siteInfo?.host,
        toolItem.siteInfo?.path,
        toolItem.siteInfo?.title,
        toolItem.siteInfo?.codeText,
        toolItem.siteInfo?.sourceText,
        toolItem.siteInfo?.expiresAt,
        toolItem.siteInfo?.statusText,
    ].join(' ');
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
        buildSearchableToolText(record.toolItem),
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

function createCopyField(label, displayValue, copyValue = displayValue, options = {}) {
    const line = document.createElement('div');
    const classNames = ['record-card__field'];
    if (options.wide) {
        classNames.push('record-card__field--wide');
    }
    if (options.compact) {
        classNames.push('record-card__field--compact');
    }
    line.className = classNames.join(' ');

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

function appendVisibleCopyFields(container, fields) {
    fields
        .filter((field) => field.required || normalizeText(field.displayValue))
        .forEach((field) => {
            container.appendChild(createCopyField(
                field.label,
                field.displayValue,
                field.copyValue,
                field.options || {}
            ));
        });
}

function createRecordActionButton(className, text, title, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = text;
    button.title = title;
    button.addEventListener('click', onClick);
    return button;
}

function buildSiteSummaryText(siteInfo) {
    if (siteInfo?.codeText) {
        return siteInfo.codeText;
    }

    if (siteInfo?.title) {
        return siteInfo.title;
    }

    return siteInfo?.statusText || '待刷新';
}

function buildLinkedResultButtonClass(resultText) {
    if (resultText === '暂无验证码') {
        return 'record-card__linked-result record-card__linked-result--empty';
    }

    if (!resultText || resultText === '待刷新') {
        return 'record-card__linked-result record-card__linked-result--pending';
    }

    return 'record-card__linked-result';
}

function createLinkedMetaLine(label, value) {
    const line = document.createElement('div');
    line.className = 'record-card__linked-meta-line';

    const strong = document.createElement('strong');
    strong.textContent = `${label}：`;

    const span = document.createElement('span');
    span.textContent = value;

    line.append(strong, span);
    return line;
}

function renderLinkedToolItem(toolItem, recordId) {
    const panel = document.createElement('section');
    panel.className = 'record-card__linked-tool';

    const resultText = buildSiteSummaryText(toolItem.siteInfo);
    const identifierCopyValue = normalizeCopyIdentifier(toolItem.identifier) || toolItem.identifier;
    const copyButton = createRecordActionButton(
        'record-card__linked-identifier',
        toolItem.identifier,
        `点击复制：${identifierCopyValue}`,
        async () => {
            const copied = await copyText(identifierCopyValue);
            setRecordFeedback(copied ? `已复制标识：${identifierCopyValue}` : '复制标识失败，请手动选择字段内容。', copied ? 'success' : 'error');
        }
    );
    copyButton.setAttribute('aria-label', `复制标识：${toolItem.identifier}`);

    const resultButton = createRecordActionButton(
        buildLinkedResultButtonClass(resultText),
        resultText,
        `点击复制结果：${resultText}`,
        async () => {
            const copied = await copyText(resultText);
            setRecordFeedback(copied ? `已复制结果：${resultText}` : '复制结果失败，请手动选择字段内容。', copied ? 'success' : 'error');
        }
    );
    resultButton.setAttribute('aria-label', `复制结果：${resultText}`);

    const openButton = createRecordActionButton(
        'record-card__linked-open',
        '↗',
        `打开地址：${toolItem.displayUrl}`,
        () => {
            window.open(toolItem.openUrl, '_blank', 'noopener,noreferrer');
        }
    );
    openButton.setAttribute('aria-label', `打开地址：${toolItem.displayUrl}`);

    const refreshButton = createRecordActionButton(
        'record-card__linked-refresh',
        '刷新',
        `刷新此数据：${toolItem.identifier}`,
        async () => {
            refreshButton.disabled = true;
            refreshButton.textContent = '刷新中';
            await refreshRecordToolItem(recordId);
        }
    );
    refreshButton.setAttribute('aria-label', `刷新此数据：${toolItem.identifier}`);

    const meta = document.createElement('div');
    meta.className = 'record-card__linked-meta';
    meta.append(
        createLinkedMetaLine('来源', toolItem.siteInfo.sourceText || '未识别'),
        createLinkedMetaLine('到期', toolItem.siteInfo.expiresAt || '未提供'),
        createLinkedMetaLine('刷新', formatCheckedAt(toolItem.siteInfo.checkedAt))
    );

    panel.append(copyButton, resultButton, openButton, meta, refreshButton);
    return panel;
}

function renderRecordCard(record) {
    const card = document.createElement('article');
    card.className = 'record-card';

    const head = document.createElement('div');
    head.className = 'record-card__head';
    const title = document.createElement('h3');
    title.className = 'record-card__title';
    const hasRecordFields = Boolean(record.rawText || record.name || record.address || record.cardNumber || record.cardExpiry || record.extraCode || record.phone || record.note);

    if (record.rawText) {
        title.textContent = '纯文本';
    } else if (record.name) {
        title.appendChild(createCopyValueButton('姓名', record.name));
    } else if (record.toolItem) {
        title.textContent = '短信数据';
    } else {
        title.textContent = '本地记录';
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
        fields.append(createCopyField('内容', record.rawText, record.rawText, { wide: true }));
    } else if (hasRecordFields) {
        appendVisibleCopyFields(fields, [
            { label: '地址', displayValue: record.address, required: true, options: { wide: true } },
            { label: '卡号', displayValue: cardDisplayValue, copyValue: record.cardNumber || record.cardLast4 || cardDisplayValue, options: { compact: true } },
            { label: '有效期', displayValue: record.cardExpiry, options: { compact: true } },
            { label: 'CVV', displayValue: record.extraCode, options: { compact: true } },
            { label: '电话', displayValue: phoneDisplayValue, options: { compact: true } },
            { label: '备注', displayValue: record.note, options: { wide: true } },
        ]);
    }

    card.append(head);
    if (fields.children.length) {
        card.appendChild(fields);
    }
    if (record.toolItem) {
        card.appendChild(renderLinkedToolItem(record.toolItem, record.id));
    }
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
    const timeoutId = window.setTimeout(() => controller.abort(), RECORD_REFRESH_TIMEOUT_MS);

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

        return Object.freeze({
            ok: response.ok,
            status: response.status,
            contentType,
            rawText,
        });
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
    return Object.freeze({
        ok: Boolean(payload.success),
        status: payload.status_code || 0,
        contentType: payload.content_type || '',
        rawText: payload.text || '',
    });
}

async function fetchPageContent(openUrl) {
    try {
        return await fetchPageContentDirect(openUrl);
    } catch (_directError) {
        return await fetchPageContentViaServer(openUrl);
    }
}

async function fetchSiteInfoForToolItem(toolItem) {
    const checkedAt = new Date().toISOString();
    const fallbackInfo = {
        sourceText: toolItem.siteInfo?.sourceText || '',
        expiresAt: toolItem.siteInfo?.expiresAt || '',
    };

    try {
        const pageContent = await fetchPageContent(toolItem.openUrl);
        if (!pageContent.ok) {
            return buildSiteInfo(toolItem.openUrl, {
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
                return buildSiteInfo(toolItem.openUrl, {
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
                return buildSiteInfo(toolItem.openUrl, {
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
        return buildSiteInfo(toolItem.openUrl, {
            ...fallbackInfo,
            codeText: '',
            sourceText: '',
            expiresAt: '',
            statusText: `已访问：${shortType}`,
            checkedAt,
        });
    } catch (error) {
        const isTimeout = error?.name === 'AbortError';
        return buildSiteInfo(toolItem.openUrl, {
            ...fallbackInfo,
            codeText: '',
            sourceText: '',
            expiresAt: '',
            statusText: isTimeout ? '刷新超时，显示网址信息' : '站点限制读取，显示网址信息',
            checkedAt,
        });
    }
}

async function refreshRecordToolItem(recordId) {
    const targetIndex = currentRecords.findIndex((record) => record.id === recordId);
    const targetRecord = currentRecords[targetIndex];
    const targetToolItem = targetRecord?.toolItem;

    if (!targetToolItem) {
        setRecordFeedback('没有找到要刷新的短信数据。', 'warning');
        renderRecords();
        return;
    }

    try {
        const nextSiteInfo = await fetchSiteInfoForToolItem(targetToolItem);
        const nextRecords = createFrozenRecords(currentRecords.map((record, index) => (
            index === targetIndex
                ? Object.freeze({
                    ...record,
                    toolItem: Object.freeze({
                        ...targetToolItem,
                        siteInfo: nextSiteInfo,
                    }),
                })
                : record
        )));
        persistRecordState(nextRecords);
        renderRecords();
        setRecordFeedback(`已刷新：${targetToolItem.identifier}`, 'success');
    } catch (_error) {
        renderRecords();
        setRecordFeedback(`刷新失败：${targetToolItem.identifier}`, 'error');
    }
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

    const countText = parseResult.toolItemCount > 0
        ? `（数据一 ${parseResult.recordCount} 条，数据二 ${parseResult.toolItemCount} 条）`
        : '';
    const skippedText = parseResult.skippedSensitive > 0 ? `，已丢弃 ${parseResult.skippedSensitive} 类敏感字段并清空输入框` : '';
    const invalidText = parseResult.invalidLines.length ? `，另有 ${parseResult.invalidLines.length} 行未导入` : '';
    setRecordFeedback(`已保存 ${parseResult.records.length} 个记录框${countText}${skippedText}${invalidText}。`, parseResult.invalidLines.length ? 'warning' : 'success');
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
