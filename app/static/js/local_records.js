const RECORD_STORAGE_KEY = 'local_record_workbench_items_v1';
const RECORD_COMBINE_STORAGE_KEY = 'local_record_workbench_combine_enabled_v1';
const RECORD_REFRESH_TIMEOUT_MS = 6000;

const recordBatchInput = document.getElementById('recordBatchInput');
const recordFeedback = document.getElementById('recordFeedback');
const importRecordWorkbenchBtn = document.getElementById('importRecordWorkbenchBtn');
const clearRecordTextareaBtn = document.getElementById('clearRecordTextareaBtn');
const clearRecordLocalDataBtn = document.getElementById('clearRecordLocalDataBtn');
const combineRecordDataToggle = document.getElementById('combineRecordDataToggle');
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

function isRecordCombineEnabled() {
    return Boolean(combineRecordDataToggle?.checked);
}

function loadRecordCombinePreference() {
    if (!combineRecordDataToggle) {
        return;
    }

    try {
        combineRecordDataToggle.checked = window.localStorage.getItem(RECORD_COMBINE_STORAGE_KEY) === '1';
    } catch (_error) {
        combineRecordDataToggle.checked = false;
    }
}

function persistRecordCombinePreference() {
    if (!combineRecordDataToggle) {
        return;
    }

    try {
        window.localStorage.setItem(RECORD_COMBINE_STORAGE_KEY, isRecordCombineEnabled() ? '1' : '0');
    } catch (_error) {
        // 偏好保存失败不影响本地记录导入。
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

function createFrozenEmailAccount(emailAccount, sequence) {
    if (!emailAccount || typeof emailAccount !== 'object') {
        return null;
    }

    const email = normalizeText(emailAccount.email);
    const sourceUrl = String(emailAccount.sourceUrl || emailAccount.apiUrl || emailAccount.uiUrl || '').trim();
    if (!email || !sourceUrl) {
        return null;
    }

    return Object.freeze({
        sequence: Number.isInteger(emailAccount.sequence) ? emailAccount.sequence : sequence,
        email,
        sourceUrl,
        displayUrl: normalizeText(emailAccount.displayUrl || buildDisplayUrl(sourceUrl)),
        sourceName: normalizeText(emailAccount.sourceName),
        uid: normalizeText(emailAccount.uid),
        password: normalizeText(emailAccount.password),
        uiUrl: String(emailAccount.uiUrl || '').trim(),
        apiUrl: String(emailAccount.apiUrl || '').trim(),
        host: normalizeText(emailAccount.host),
        statusText: normalizeText(emailAccount.statusText || '待取件'),
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
        const emailAccount = createFrozenEmailAccount(record.emailAccount, sequence);

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
            emailAccount,
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
        emailAccount: createFrozenEmailAccount(values.emailAccount, sequence),
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

function isLikelyEmailAccountLine(line) {
    if (!isValidHttpUrl(line)) {
        return false;
    }

    try {
        const parsedUrl = new URL(String(line || '').trim());
        const path = parsedUrl.pathname.toLowerCase();
        const hasEmailParam = ['email', 'u', 'mail', 'account'].some((name) => parsedUrl.searchParams.has(name));
        const hasEmailPath = (
            path.includes('mail_onek.php') ||
            path.endsWith('/m.php') ||
            path.endsWith('m.php') ||
            path.includes('/eid/')
        );
        return hasEmailParam || hasEmailPath;
    } catch (_error) {
        return false;
    }
}

function parseEmailAccountLine(line, sequence) {
    if (typeof parseEmailAccountBatch === 'function') {
        const parsedEmail = parseEmailAccountBatch(line);
        if (parsedEmail.accounts.length) {
            return {
                emailAccounts: parsedEmail.accounts,
                emailSourceLinks: [],
                skippedSensitive: 0,
            };
        }

        if (parsedEmail.sourceLinks.length) {
            return {
                emailAccounts: [],
                emailSourceLinks: parsedEmail.sourceLinks,
                skippedSensitive: 0,
            };
        }

        return { error: parsedEmail.invalidLines[0]?.reason || '邮箱链接格式未识别' };
    }

    try {
        const parsedUrl = new URL(String(line || '').trim());
        const email = normalizeText(parsedUrl.searchParams.get('email') || parsedUrl.searchParams.get('u') || parsedUrl.searchParams.get('mail') || parsedUrl.searchParams.get('account'));
        if (!email) {
            return { error: '邮箱链接缺少邮箱参数' };
        }

        const password = normalizeText(parsedUrl.searchParams.get('pass') || parsedUrl.searchParams.get('p') || parsedUrl.searchParams.get('password'));
        return {
            emailAccounts: [Object.freeze({
                sequence,
                email,
                sourceUrl: parsedUrl.toString(),
                displayUrl: buildDisplayUrl(parsedUrl.toString()),
                sourceName: normalizeText(parsedUrl.searchParams.get('n') || parsedUrl.searchParams.get('name') || parsedUrl.searchParams.get('file')),
                uid: normalizeText(parsedUrl.searchParams.get('uid') || parsedUrl.searchParams.get('id')),
                password,
                uiUrl: '',
                apiUrl: parsedUrl.pathname.includes('mail_onek.php') ? parsedUrl.toString() : '',
                host: parsedUrl.hostname || parsedUrl.host || '未知站点',
                statusText: '待取件',
            })],
            emailSourceLinks: [],
            skippedSensitive: 0,
        };
    } catch (_error) {
        return { error: '邮箱链接格式未识别' };
    }
}

function createFrozenRecordEmailAccounts(emailAccounts) {
    return Object.freeze((emailAccounts || [])
        .filter(Boolean)
        .map((emailAccount, index) => createFrozenEmailAccount({
            ...emailAccount,
            sequence: index + 1,
        }, index + 1))
        .filter(Boolean));
}

function combineRecordsAndToolItems(records, toolItems, emailAccounts = []) {
    const maxCount = Math.max(records.length, toolItems.length, emailAccounts.length);
    return Object.freeze(Array.from({ length: maxCount }, (_unused, index) => {
        const record = records[index];
        const toolItem = toolItems[index] || null;
        const emailAccount = emailAccounts[index] || null;
        const sequence = index + 1;

        if (record) {
            return Object.freeze({
                ...record,
                sequence,
                toolItem,
                emailAccount,
            });
        }

        return buildRecord({
            sequence,
            toolItem,
            emailAccount,
        });
    }));
}

function hasRecordData(record) {
    return Boolean(
        record?.rawText ||
        record?.name ||
        record?.address ||
        record?.cardNumber ||
        record?.cardMasked ||
        record?.cardLast4 ||
        record?.cardExpiry ||
        record?.extraCode ||
        record?.phone ||
        record?.phoneMasked ||
        record?.note ||
        (Array.isArray(record?.warnings) && record.warnings.length)
    );
}

function stripToolItemFromRecord(record, index) {
    return Object.freeze({
        ...record,
        sequence: index + 1,
        toolItem: null,
        emailAccount: null,
    });
}

function extractRecordData(records) {
    return createFrozenRecords((records || [])
        .filter(hasRecordData)
        .map(stripToolItemFromRecord));
}

function createFrozenToolItems(toolItems) {
    return Object.freeze((toolItems || [])
        .filter(Boolean)
        .map((toolItem, index) => createFrozenToolItem({
            ...toolItem,
            sequence: index + 1,
        }, index + 1))
        .filter(Boolean));
}

function extractToolItems(records) {
    return createFrozenToolItems((records || []).map((record) => record?.toolItem));
}

function extractEmailAccounts(records) {
    return createFrozenRecordEmailAccounts((records || []).map((record) => record?.emailAccount));
}

function mergeRecordImportResult(existingRecords, parseResult) {
    const importedRecords = Array.isArray(parseResult?.sourceRecords)
        ? parseResult.sourceRecords
        : [];
    const importedToolItems = Array.isArray(parseResult?.sourceToolItems)
        ? parseResult.sourceToolItems
        : [];
    const importedEmailAccounts = Array.isArray(parseResult?.sourceEmailAccounts)
        ? parseResult.sourceEmailAccounts
        : [];
    const existingRecordData = extractRecordData(existingRecords);
    const existingToolItems = extractToolItems(existingRecords);
    const existingEmailAccounts = extractEmailAccounts(existingRecords);
    const nextRecordData = parseResult?.recordCount > 0 ? importedRecords : existingRecordData;
    const nextToolItems = parseResult?.toolItemCount > 0 ? importedToolItems : existingToolItems;
    const nextEmailAccounts = parseResult?.emailAccountCount > 0 ? importedEmailAccounts : existingEmailAccounts;

    return createFrozenRecords(combineRecordsAndToolItems(nextRecordData, nextToolItems, nextEmailAccounts));
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

function parseRecordBatch(content, options = {}) {
    const combineEnabled = Boolean(options.combineEnabled);
    const lines = String(content || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);

    const parsed = lines.reduce((result, line, index) => {
        if (!combineEnabled && (shouldParseAsLocalToolLine(line) || isLikelyEmailAccountLine(line))) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems,
                emailAccounts: result.emailAccounts,
                emailSourceLinks: result.emailSourceLinks,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: '请先开启三种数据合一后再导入数据二或邮箱数据' }]),
                skippedSensitive: result.skippedSensitive,
            });
        }

        const parsedLine = (() => {
            if (combineEnabled && shouldParseAsLocalToolLine(line)) {
                return parseLocalToolLine(line, result.toolItems.length + 1);
            }

            if (combineEnabled && isLikelyEmailAccountLine(line)) {
                return parseEmailAccountLine(line, result.emailAccounts.length + result.emailSourceLinks.length + 1);
            }

            return parseRecordLine(line, result.records.length + 1);
        })();
        if (parsedLine.error) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems,
                emailAccounts: result.emailAccounts,
                emailSourceLinks: result.emailSourceLinks,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason: parsedLine.error }]),
                skippedSensitive: result.skippedSensitive,
            });
        }

        if (parsedLine.toolItem) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems.concat([parsedLine.toolItem]),
                emailAccounts: result.emailAccounts,
                emailSourceLinks: result.emailSourceLinks,
                invalidLines: result.invalidLines,
                skippedSensitive: result.skippedSensitive,
            });
        }

        if (parsedLine.emailAccounts) {
            return Object.freeze({
                records: result.records,
                toolItems: result.toolItems,
                emailAccounts: result.emailAccounts.concat(parsedLine.emailAccounts),
                emailSourceLinks: result.emailSourceLinks.concat(parsedLine.emailSourceLinks || []),
                invalidLines: result.invalidLines,
                skippedSensitive: result.skippedSensitive,
            });
        }

        return Object.freeze({
            records: result.records.concat([parsedLine.record]),
            toolItems: result.toolItems,
            emailAccounts: result.emailAccounts,
            emailSourceLinks: result.emailSourceLinks,
            invalidLines: result.invalidLines,
            skippedSensitive: result.skippedSensitive + (parsedLine.skippedSensitive || 0),
        });
    }, Object.freeze({ records: [], toolItems: [], emailAccounts: [], emailSourceLinks: [], invalidLines: [], skippedSensitive: 0 }));

    const sourceRecords = createFrozenRecords(parsed.records);
    const sourceToolItems = createFrozenToolItems(parsed.toolItems);
    const sourceEmailAccounts = createFrozenRecordEmailAccounts(parsed.emailAccounts);
    const combinedRecords = combineEnabled
        ? combineRecordsAndToolItems(sourceRecords, sourceToolItems, sourceEmailAccounts)
        : sourceRecords;

    return Object.freeze({
        records: createFrozenRecords(combinedRecords),
        invalidLines: Object.freeze(parsed.invalidLines.map((item) => Object.freeze(item))),
        skippedSensitive: parsed.skippedSensitive,
        recordCount: parsed.records.length,
        toolItemCount: combineEnabled ? parsed.toolItems.length : 0,
        emailAccountCount: combineEnabled ? sourceEmailAccounts.length : 0,
        sourceEmailLinkCount: combineEnabled ? parsed.emailSourceLinks.length : 0,
        sourceRecords,
        sourceToolItems: combineEnabled ? sourceToolItems : Object.freeze([]),
        sourceEmailAccounts: combineEnabled ? sourceEmailAccounts : Object.freeze([]),
        sourceEmailLinks: combineEnabled ? Object.freeze(parsed.emailSourceLinks.map((item) => Object.freeze(item))) : Object.freeze([]),
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
            const hasEmailAccount = typeof record?.emailAccount?.email === 'string' && typeof record?.emailAccount?.sourceUrl === 'string';
            return hasStructuredFields || hasPlainTextField || hasToolItem || hasEmailAccount;
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
            emailAccount: record.emailAccount,
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

function buildSearchableEmailText(emailAccount) {
    if (!emailAccount) {
        return '';
    }

    return [
        emailAccount.email,
        emailAccount.sourceUrl,
        emailAccount.displayUrl,
        emailAccount.sourceName,
        emailAccount.uid,
        emailAccount.host,
        emailAccount.apiUrl,
        emailAccount.uiUrl,
        emailAccount.statusText,
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
        buildSearchableEmailText(record.emailAccount),
    ].join(' ').toLowerCase();
}

function bindCopyableRecordElement(element, label, displayValue, copyValue = displayValue) {
    const safeDisplayValue = normalizeText(displayValue);
    const safeCopyValue = typeof copyValue === 'string' ? copyValue.trim() : safeDisplayValue;
    const finalCopyValue = safeCopyValue || safeDisplayValue;

    element.tabIndex = 0;
    element.setAttribute('role', 'button');
    element.title = `点击复制${label}`;
    element.setAttribute('aria-label', `点击复制${label}：${safeDisplayValue}`);
    element.dataset.copyValue = finalCopyValue;
    element.addEventListener('click', async () => {
        const copied = await copyText(finalCopyValue);
        setRecordFeedback(copied ? `已复制${label}。` : `复制${label}失败，请手动选择字段内容。`, copied ? 'success' : 'error');
    });
    element.addEventListener('keydown', (event) => {
        if (!['Enter', ' '].includes(event.key)) {
            return;
        }

        event.preventDefault();
        element.click();
    });
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

    const strong = document.createElement('strong');
    strong.textContent = `${label}：`;

    const safeDisplayValue = normalizeText(displayValue);
    const safeCopyValue = typeof copyValue === 'string' ? copyValue.trim() : safeDisplayValue;
    const finalCopyValue = safeCopyValue || safeDisplayValue;
    const valueElement = document.createElement('span');

    if (safeDisplayValue) {
        classNames.push('record-card__field--copyable');
        bindCopyableRecordElement(line, label, safeDisplayValue, finalCopyValue);
        valueElement.className = 'record-card__copy-value';
        valueElement.textContent = safeDisplayValue;
    } else {
        valueElement.className = 'record-card__empty-value';
        valueElement.textContent = '未保存';
    }

    line.className = classNames.join(' ');
    line.append(strong, valueElement);
    return line;
}

function appendCopyableTitleValue(title, label, displayValue, copyValue = displayValue) {
    const safeDisplayValue = normalizeText(displayValue);
    title.classList.add('record-card__title--copyable');
    bindCopyableRecordElement(title, label, safeDisplayValue, copyValue);

    const valueElement = document.createElement('span');
    valueElement.className = 'record-card__copy-value';
    valueElement.textContent = safeDisplayValue;
    title.appendChild(valueElement);
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
        `点击刷新并复制结果：${resultText}`,
        async () => {
            await refreshAndCopyToolItemResult(recordId, resultButton);
        }
    );
    resultButton.setAttribute('aria-label', `刷新并复制结果：${resultText}`);

    const openButton = createRecordActionButton(
        'record-card__linked-open',
        '↗',
        `打开地址：${toolItem.displayUrl}`,
        () => {
            window.open(toolItem.openUrl, '_blank', 'noopener,noreferrer');
        }
    );
    openButton.setAttribute('aria-label', `打开地址：${toolItem.displayUrl}`);

    panel.append(copyButton, resultButton, openButton);
    return panel;
}

function buildEmailAccountMetaText(emailAccount) {
    if (emailAccount.sourceName && emailAccount.host) {
        return `${emailAccount.host} · ${emailAccount.sourceName}`;
    }

    return emailAccount.host || emailAccount.displayUrl || '邮箱';
}

function renderLinkedEmailAccount(emailAccount) {
    const panel = document.createElement('section');
    panel.className = 'record-card__linked-email';

    const copyButton = createRecordActionButton(
        'record-card__linked-email-address',
        emailAccount.email,
        `点击复制邮箱：${emailAccount.email}`,
        async () => {
            const copied = await copyText(emailAccount.email);
            setRecordFeedback(copied ? `已复制邮箱：${emailAccount.email}` : '复制邮箱失败，请手动选择字段内容。', copied ? 'success' : 'error');
        }
    );
    copyButton.setAttribute('aria-label', `复制邮箱：${emailAccount.email}`);

    const meta = document.createElement('span');
    meta.className = 'record-card__linked-email-meta';
    meta.textContent = buildEmailAccountMetaText(emailAccount);

    panel.append(copyButton, meta);
    return panel;
}

function renderRecordCard(record) {
    const card = document.createElement('article');
    card.className = 'record-card';

    const head = document.createElement('div');
    head.className = 'record-card__head';
    const title = document.createElement('h3');
    title.className = 'record-card__title';
    const hasRecordFields = Boolean(record.rawText || record.name || record.address || record.cardNumber || record.cardExpiry || record.extraCode || record.phone);

    if (record.rawText) {
        title.textContent = '纯文本';
    } else if (record.name) {
        appendCopyableTitleValue(title, '姓名', record.name);
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
        ]);
    }

    card.append(head);
    if (fields.children.length) {
        card.appendChild(fields);
    }
    if (record.toolItem) {
        card.appendChild(renderLinkedToolItem(record.toolItem, record.id));
    }
    if (record.emailAccount) {
        card.appendChild(renderLinkedEmailAccount(record.emailAccount));
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

async function discoverEmailAccountsForRecordSource(sourceLink) {
    if (typeof discoverEmailAccountsFromPage !== 'function') {
        throw new Error('email-discovery-unavailable');
    }

    const pageContent = await fetchPageContent(sourceLink.sourceUrl);
    if (!pageContent.ok) {
        throw new Error(`HTTP ${pageContent.status}`);
    }

    const accounts = discoverEmailAccountsFromPage(
        pageContent.rawText,
        pageContent.contentType,
        sourceLink.sourceUrl,
        sourceLink
    );

    if (!accounts.length) {
        throw new Error('missing-email-password');
    }

    return accounts;
}

async function expandRecordEmailSourceLinks(parseResult) {
    const sourceLinks = Array.isArray(parseResult?.sourceEmailLinks) ? parseResult.sourceEmailLinks : [];
    if (!sourceLinks.length) {
        return parseResult;
    }

    const discoveryResults = await Promise.all(sourceLinks.map(async (sourceLink) => {
        try {
            return Object.freeze({
                accounts: await discoverEmailAccountsForRecordSource(sourceLink),
                invalidLines: [],
            });
        } catch (error) {
            const reason = error.message === 'missing-email-password'
                ? '邮箱入口链接未识别到邮箱和密码'
                : `邮箱入口链接读取失败：${error.message}`;
            return Object.freeze({
                accounts: [],
                invalidLines: [{ lineNumber: sourceLink.lineNumber || sourceLink.sequence, reason }],
            });
        }
    }));

    const discoveredAccounts = createFrozenRecordEmailAccounts(discoveryResults.flatMap((result) => result.accounts));
    const sourceEmailAccounts = createFrozenRecordEmailAccounts((parseResult.sourceEmailAccounts || []).concat(discoveredAccounts));
    const combinedRecords = combineRecordsAndToolItems(
        parseResult.sourceRecords || [],
        parseResult.sourceToolItems || [],
        sourceEmailAccounts
    );

    return Object.freeze({
        ...parseResult,
        records: createFrozenRecords(combinedRecords),
        invalidLines: Object.freeze(parseResult.invalidLines.concat(discoveryResults.flatMap((result) => result.invalidLines)).map((item) => Object.freeze(item))),
        emailAccountCount: sourceEmailAccounts.length,
        sourceEmailAccounts,
        sourceEmailLinks: Object.freeze([]),
        sourceEmailLinkCount: 0,
    });
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

async function refreshAndCopyToolItemResult(recordId, resultButton) {
    const targetIndex = currentRecords.findIndex((record) => record.id === recordId);
    const targetRecord = currentRecords[targetIndex];
    const targetToolItem = targetRecord?.toolItem;

    if (!targetToolItem) {
        setRecordFeedback('没有找到要刷新的短信数据。', 'warning');
        renderRecords();
        return;
    }

    resultButton.disabled = true;
    resultButton.textContent = '刷新中';

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

        const nextResultText = buildSiteSummaryText(nextSiteInfo);
        const copied = await copyText(nextResultText);
        setRecordFeedback(
            copied
                ? `已刷新并复制结果：${nextResultText}`
                : `已刷新：${targetToolItem.identifier}，复制结果失败，请手动选择字段内容。`,
            copied ? 'success' : 'warning'
        );
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

    const combineEnabled = isRecordCombineEnabled();
    let parseResult = parseRecordBatch(content, { combineEnabled });
    if (combineEnabled && parseResult.sourceEmailLinkCount > 0) {
        importRecordWorkbenchBtn.disabled = true;
        importRecordWorkbenchBtn.textContent = '读取邮箱入口中';
        setRecordFeedback('正在读取邮箱入口链接并识别邮箱密码…', 'warning');
        try {
            parseResult = await expandRecordEmailSourceLinks(parseResult);
        } finally {
            importRecordWorkbenchBtn.disabled = false;
            importRecordWorkbenchBtn.textContent = '解析并保存到本地';
        }
    }
    currentInvalidLines = parseResult.invalidLines;

    if (!parseResult.records.length) {
        renderRecords();
        setRecordFeedback(combineEnabled
            ? '没有解析出有效记录，请检查分隔符、字段顺序、数据二地址或邮箱入口。'
            : '没有解析出有效记录；如需导入数据二或邮箱数据，请先开启“三种数据合一”。', 'error');
        return;
    }

    const nextRecords = combineEnabled
        ? mergeRecordImportResult(currentRecords, parseResult)
        : parseResult.records;
    persistRecordState(nextRecords);
    if (parseResult.skippedSensitive > 0) {
        recordBatchInput.value = '';
    }
    renderRecords();

    const countText = combineEnabled
        ? `（本次导入：数据一 ${parseResult.recordCount} 条，数据二 ${parseResult.toolItemCount} 条，邮箱 ${parseResult.emailAccountCount} 条）`
        : '';
    const skippedText = parseResult.skippedSensitive > 0 ? `，已丢弃 ${parseResult.skippedSensitive} 类敏感字段并清空输入框` : '';
    const invalidText = parseResult.invalidLines.length ? `，另有 ${parseResult.invalidLines.length} 行未导入` : '';
    setRecordFeedback(`已保存 ${nextRecords.length} 个记录框${countText}${skippedText}${invalidText}。`, parseResult.invalidLines.length ? 'warning' : 'success');
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

if (combineRecordDataToggle) {
    combineRecordDataToggle.addEventListener('change', () => {
        persistRecordCombinePreference();
        setRecordFeedback(isRecordCombineEnabled()
            ? '已开启三种数据合一：可导入数据二和邮箱数据，并会与现有数据一按顺序合并。'
            : '已关闭三种数据合一：导入内容将按数据一解析。', 'success');
    });
}

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

loadRecordCombinePreference();
loadRecordState();
renderRecords();
