const EMAIL_REGEX = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

function normalizeEmailText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function decodeBasicHtmlEntities(value) {
    return String(value || '')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'");
}

function stripHtmlTags(value) {
    return decodeBasicHtmlEntities(String(value || '').replace(/<[^>]+>/g, ' '));
}

function firstEmailFromText(value) {
    const match = decodeURIComponent(String(value || '')).match(EMAIL_REGEX);
    return match ? match[0] : '';
}

function firstParamValue(parsedUrl, names) {
    const matchedName = names.find((name) => parsedUrl.searchParams.get(name));
    return matchedName ? parsedUrl.searchParams.get(matchedName).trim() : '';
}

function buildEmailDisplayUrl(url) {
    try {
        const parsed = new URL(url);
        return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
    } catch (_error) {
        return '';
    }
}

function buildInboxInfo(overrides = {}) {
    return Object.freeze({
        summary: '',
        copyText: '',
        messageCount: 0,
        checkedAt: '',
        statusText: '待取件',
        ...overrides,
    });
}

function buildMailJsonApiUrl(baseUrl, email, password) {
    if (!email || !password) {
        return '';
    }

    try {
        const parsedBase = new URL(baseUrl);
        const apiUrl = new URL('/api/mail_onek.php', parsedBase.origin);
        apiUrl.searchParams.set('email', email);
        apiUrl.searchParams.set('pass', password);
        apiUrl.searchParams.set('json', '1');
        return apiUrl.toString();
    } catch (_error) {
        return '';
    }
}

function buildMailUiUrl(baseUrl, email, password) {
    if (!email || !password) {
        return '';
    }

    try {
        const parsedBase = new URL(baseUrl);
        const uiUrl = new URL('/m.php', parsedBase.origin);
        uiUrl.searchParams.set('u', email);
        uiUrl.searchParams.set('p', password);
        return uiUrl.toString();
    } catch (_error) {
        return '';
    }
}

function createFrozenEmailAccounts(accounts) {
    return Object.freeze(accounts.map((account, index) => Object.freeze({
        sequence: Number.isInteger(account.sequence) ? account.sequence : index + 1,
        email: String(account.email || ''),
        sourceUrl: String(account.sourceUrl || ''),
        displayUrl: String(account.displayUrl || buildEmailDisplayUrl(account.sourceUrl || '')),
        sourceName: String(account.sourceName || ''),
        uid: String(account.uid || ''),
        password: String(account.password || ''),
        uiUrl: String(account.uiUrl || ''),
        apiUrl: String(account.apiUrl || ''),
        host: String(account.host || ''),
        statusText: String(account.statusText || '待取件'),
        inbox: buildInboxInfo(account.inbox || {}),
    })));
}

function createEmailSourceLinkFromUrl(rawUrl, lineNumber) {
    const sourceUrl = String(rawUrl || '').trim();
    const parsedUrl = new URL(sourceUrl);

    if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        throw new Error('invalid-protocol');
    }

    return Object.freeze({
        sequence: lineNumber,
        lineNumber,
        sourceUrl,
        displayUrl: buildEmailDisplayUrl(sourceUrl),
        sourceName: firstParamValue(parsedUrl, ['n', 'name', 'file']),
        uid: firstParamValue(parsedUrl, ['uid', 'id']),
        host: parsedUrl.hostname || parsedUrl.host || '未知站点',
    });
}

function createEmailAccountFromUrl(rawUrl, sequence) {
    const sourceUrl = String(rawUrl || '').trim();
    const parsedUrl = new URL(sourceUrl);

    if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        throw new Error('invalid-protocol');
    }

    const email = firstParamValue(parsedUrl, ['email', 'u', 'mail', 'account']) || firstEmailFromText(sourceUrl);
    if (!email) {
        throw new Error('missing-email');
    }

    const password = firstParamValue(parsedUrl, ['pass', 'p', 'password']);
    const apiUrl = parsedUrl.pathname.includes('mail_onek.php') ? sourceUrl : '';
    const uiUrl = parsedUrl.pathname.endsWith('/m.php') || parsedUrl.pathname.endsWith('m.php') ? sourceUrl : '';
    const nextApiUrl = apiUrl || buildMailJsonApiUrl(sourceUrl, email, password);
    const nextUiUrl = uiUrl || buildMailUiUrl(sourceUrl, email, password);

    return Object.freeze({
        sequence,
        email,
        sourceUrl,
        displayUrl: buildEmailDisplayUrl(sourceUrl),
        sourceName: firstParamValue(parsedUrl, ['n', 'name', 'file']),
        uid: firstParamValue(parsedUrl, ['uid', 'id']),
        password,
        uiUrl: nextUiUrl,
        apiUrl: nextApiUrl,
        host: parsedUrl.hostname || parsedUrl.host || '未知站点',
        statusText: '待取件',
        inbox: buildInboxInfo(),
    });
}

function parseEmailAccountBatch(content) {
    const lines = String(content || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line);

    const parsedResult = lines.reduce((result, line, index) => {
        try {
            const account = createEmailAccountFromUrl(line, result.accounts.length + 1);
            return {
                accounts: result.accounts.concat([account]),
                sourceLinks: result.sourceLinks,
                invalidLines: result.invalidLines,
            };
        } catch (error) {
            if (error.message === 'missing-email') {
                try {
                    const sourceLink = createEmailSourceLinkFromUrl(line, index + 1);
                    return {
                        accounts: result.accounts,
                        sourceLinks: result.sourceLinks.concat([sourceLink]),
                        invalidLines: result.invalidLines,
                    };
                } catch (_sourceError) {
                    // 继续按无效行处理。
                }
            }

            const reason = error.message === 'missing-email'
                ? '未识别邮箱参数 email/u'
                : '不是有效的 http/https 取件网址';
            return {
                ...result,
                invalidLines: result.invalidLines.concat([{ lineNumber: index + 1, reason }]),
            };
        }
    }, { accounts: [], sourceLinks: [], invalidLines: [] });

    return Object.freeze({
        accounts: createFrozenEmailAccounts(parsedResult.accounts),
        sourceLinks: Object.freeze(parsedResult.sourceLinks.map((item) => Object.freeze(item))),
        invalidLines: Object.freeze(parsedResult.invalidLines.map((item) => Object.freeze(item))),
    });
}


function normalizeDiscoveredUrl(value, baseUrl) {
    const cleanedValue = decodeBasicHtmlEntities(value)
        .trim()
        .replace(/[\])}>,，。；;]+$/g, '');

    try {
        return new URL(cleanedValue, baseUrl).toString();
    } catch (_error) {
        return '';
    }
}

function collectCandidateUrls(rawText, baseUrl) {
    const text = decodeBasicHtmlEntities(rawText);
    const hrefMatches = Array.from(text.matchAll(/href\s*=\s*["']([^"']+)["']/gi)).map((match) => match[1]);
    const plainMatches = Array.from(text.matchAll(/https?:\/\/[^\s"'<>]+/gi)).map((match) => match[0]);
    const candidates = [baseUrl].concat(hrefMatches, plainMatches)
        .map((value) => normalizeDiscoveredUrl(value, baseUrl))
        .filter(Boolean);

    return Object.freeze(Array.from(new Set(candidates)));
}

function parseUrlMetadata(url) {
    try {
        const parsedUrl = new URL(url);
        return Object.freeze({
            email: firstParamValue(parsedUrl, ['email', 'u', 'mail', 'account']) || firstEmailFromText(url),
            password: firstParamValue(parsedUrl, ['pass', 'p', 'password']),
            uid: firstParamValue(parsedUrl, ['uid', 'id']),
            sourceName: firstParamValue(parsedUrl, ['n', 'name', 'file']),
            host: parsedUrl.hostname || parsedUrl.host || '',
        });
    } catch (_error) {
        return Object.freeze({ email: '', password: '', uid: '', sourceName: '', host: '' });
    }
}

function createCredentialPairFromUrl(url) {
    const metadata = parseUrlMetadata(url);
    if (!metadata.email || !metadata.password) {
        return null;
    }

    try {
        const parsedUrl = new URL(url);
        return Object.freeze({
            email: metadata.email,
            password: metadata.password,
            uiUrl: parsedUrl.pathname.endsWith('/m.php') ? url : '',
            apiUrl: parsedUrl.pathname.includes('mail_onek.php') ? url : '',
            host: metadata.host,
        });
    } catch (_error) {
        return null;
    }
}

function collectTextCredentialPairs(rawText) {
    const text = normalizeEmailText(stripHtmlTags(rawText));
    const emails = Array.from(new Set(
        Array.from(text.matchAll(new RegExp(EMAIL_REGEX, 'gi'))).map((match) => match[0])
    ));
    const passwords = Array.from(new Set(
        Array.from(text.matchAll(/(?:邮箱密码|密码|password|pass)\s*[:=：]\s*([A-Za-z0-9._!@#$%^&*+-]{3,80})/gi))
            .map((match) => match[1])
    ));

    if (emails.length !== 1 || passwords.length !== 1) {
        return Object.freeze([]);
    }

    return Object.freeze([Object.freeze({
        email: emails[0],
        password: passwords[0],
        uiUrl: '',
        apiUrl: '',
        host: '',
    })]);
}

function dedupeCredentialPairs(pairs) {
    return Object.freeze(pairs.reduce((result, pair) => {
        if (!pair || !pair.email || !pair.password) {
            return result;
        }

        const key = `${pair.email.toLowerCase()}|${pair.password}`;
        if (result.keys.includes(key)) {
            return result;
        }

        return {
            keys: result.keys.concat([key]),
            pairs: result.pairs.concat([Object.freeze(pair)]),
        };
    }, { keys: [], pairs: [] }).pairs);
}

function discoverEmailAccountsFromPage(rawText, contentType = '', baseUrl = '', fallbackAccount = {}) {
    const candidates = collectCandidateUrls(rawText, baseUrl || fallbackAccount.sourceUrl || 'http://localhost/');
    const credentialPairs = dedupeCredentialPairs(
        candidates.map(createCredentialPairFromUrl)
            .concat(collectTextCredentialPairs(rawText))
    );
    const sourceMetadata = parseUrlMetadata(baseUrl || fallbackAccount.sourceUrl || '');

    return createFrozenEmailAccounts(credentialPairs.map((pair, index) => Object.freeze({
        sequence: index + 1,
        email: pair.email,
        sourceUrl: fallbackAccount.sourceUrl || baseUrl,
        displayUrl: buildEmailDisplayUrl(fallbackAccount.sourceUrl || baseUrl),
        sourceName: sourceMetadata.sourceName || fallbackAccount.sourceName || '',
        uid: sourceMetadata.uid || fallbackAccount.uid || '',
        password: pair.password,
        uiUrl: pair.uiUrl || buildMailUiUrl(pair.apiUrl || baseUrl, pair.email, pair.password),
        apiUrl: pair.apiUrl || buildMailJsonApiUrl(pair.uiUrl || baseUrl, pair.email, pair.password),
        host: pair.host || sourceMetadata.host || fallbackAccount.host || '',
        statusText: '待取件',
        inbox: buildInboxInfo(),
    })));
}

function discoverEmailApiLinks(rawText, contentType = '', baseUrl = '', fallbackAccount = {}) {
    const candidates = collectCandidateUrls(rawText, baseUrl || fallbackAccount.sourceUrl || 'http://localhost/');
    const apiUrl = candidates.find((url) => {
        try {
            const parsedUrl = new URL(url);
            return parsedUrl.pathname.includes('mail_onek.php') || (
                parsedUrl.pathname.includes('/api/') &&
                (parsedUrl.searchParams.has('json') || parsedUrl.searchParams.has('email'))
            );
        } catch (_error) {
            return false;
        }
    }) || '';
    const uiUrl = candidates.find((url) => {
        try {
            return new URL(url).pathname.endsWith('/m.php');
        } catch (_error) {
            return false;
        }
    }) || '';

    const sourceMetadata = parseUrlMetadata(baseUrl || fallbackAccount.sourceUrl || '');
    const apiMetadata = parseUrlMetadata(apiUrl);
    const uiMetadata = parseUrlMetadata(uiUrl);
    const textEmail = firstEmailFromText(rawText);
    const text = normalizeEmailText(stripHtmlTags(rawText));
    const looksLikeJson = String(contentType || '').toLowerCase().includes('json');
    const email = apiMetadata.email || uiMetadata.email || sourceMetadata.email || fallbackAccount.email || textEmail;
    const password = apiMetadata.password || uiMetadata.password || sourceMetadata.password || fallbackAccount.password || '';
    const generatedApiUrl = apiUrl || buildMailJsonApiUrl(uiUrl || baseUrl, email, password);
    const generatedUiUrl = uiUrl || buildMailUiUrl(apiUrl || baseUrl, email, password);

    return Object.freeze({
        email,
        password,
        uid: sourceMetadata.uid || fallbackAccount.uid || '',
        sourceName: sourceMetadata.sourceName || fallbackAccount.sourceName || '',
        host: apiMetadata.host || uiMetadata.host || sourceMetadata.host || fallbackAccount.host || '',
        uiUrl: generatedUiUrl || fallbackAccount.uiUrl || '',
        apiUrl: generatedApiUrl || (looksLikeJson ? baseUrl : '') || fallbackAccount.apiUrl || '',
        pageText: text,
    });
}

function extractMessageField(message, fieldNames) {
    if (!message || typeof message !== 'object') {
        return '';
    }

    const matchedKey = Object.keys(message).find((key) => fieldNames.includes(key.toLowerCase()));
    const value = matchedKey ? message[matchedKey] : '';
    if (typeof value === 'string' || typeof value === 'number') {
        return normalizeEmailText(stripHtmlTags(value));
    }

    return '';
}

function normalizeJsonMessage(value) {
    if (typeof value === 'string') {
        const text = normalizeEmailText(stripHtmlTags(value));
        return text ? Object.freeze({ from: '', subject: '', time: '', content: text }) : null;
    }

    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null;
    }

    const from = extractMessageField(value, ['from', 'sender', 'fromname', 'from_email', 'mailfrom']);
    const subject = extractMessageField(value, ['subject', 'title', 'name']);
    const time = extractMessageField(value, ['date', 'time', 'created_at', 'created', 'sendtime']);
    const content = extractMessageField(value, ['content', 'body', 'html', 'text', 'message', 'mailcontent']);

    if (!from && !subject && !time && !content) {
        return null;
    }

    return Object.freeze({ from, subject, time, content });
}

function collectJsonMessages(value, depth = 0) {
    if (depth > 5) {
        return Object.freeze([]);
    }

    if (Array.isArray(value)) {
        return Object.freeze(value.reduce((messages, item) => {
            const normalizedMessage = normalizeJsonMessage(item);
            if (normalizedMessage) {
                return messages.concat([normalizedMessage]);
            }

            return messages.concat(collectJsonMessages(item, depth + 1));
        }, []));
    }

    if (!value || typeof value !== 'object') {
        return Object.freeze([]);
    }

    const preferredKeys = ['data', 'list', 'lists', 'mail', 'mails', 'message', 'messages', 'rows', 'result'];
    const preferredMessages = preferredKeys.reduce((messages, key) => {
        if (Object.prototype.hasOwnProperty.call(value, key)) {
            return messages.concat(collectJsonMessages(value[key], depth + 1));
        }
        return messages;
    }, []);

    if (preferredMessages.length) {
        return Object.freeze(preferredMessages);
    }

    const directMessage = normalizeJsonMessage(value);
    if (directMessage) {
        return Object.freeze([directMessage]);
    }

    return Object.freeze(Object.keys(value).reduce((messages, key) => (
        messages.concat(collectJsonMessages(value[key], depth + 1))
    ), []));
}

function buildMessageCopyText(messages) {
    return messages.slice(0, 3).map((message, index) => [
        `#${index + 1}`,
        message.from ? `发件人：${message.from}` : '',
        message.subject ? `主题：${message.subject}` : '',
        message.time ? `时间：${message.time}` : '',
        message.content ? `内容：${message.content}` : '',
    ].filter(Boolean).join('\n')).join('\n\n');
}

function parseInboxContent(rawText, contentType = '') {
    const rawValue = String(rawText || '').trim();
    const normalizedContentType = String(contentType || '').toLowerCase();
    const shouldParseJson = normalizedContentType.includes('json') || /^[{[]/.test(rawValue);

    if (shouldParseJson) {
        try {
            const parsedJson = JSON.parse(rawValue);
            const messages = collectJsonMessages(parsedJson);
            if (messages.length) {
                const firstMessage = messages[0];
                const firstSummary = firstMessage.subject || firstMessage.content || firstMessage.from || '最新邮件';
                return buildInboxInfo({
                    summary: `已取件 ${messages.length} 封：${firstSummary.slice(0, 80)}`,
                    copyText: buildMessageCopyText(messages),
                    messageCount: messages.length,
                    statusText: '已取件',
                });
            }

            const jsonText = normalizeEmailText(JSON.stringify(parsedJson));
            const emptySummary = /暂无|没有|empty|not found/i.test(jsonText) ? '暂无邮件' : `已读取响应：${jsonText.slice(0, 120)}`;
            return buildInboxInfo({
                summary: emptySummary,
                copyText: JSON.stringify(parsedJson, null, 2).slice(0, 4000),
                messageCount: 0,
                statusText: emptySummary === '暂无邮件' ? '暂无邮件' : '已取件',
            });
        } catch (_error) {
            // 继续按文本解析。
        }
    }

    const readableText = normalizeEmailText(stripHtmlTags(rawValue));
    if (!readableText) {
        return buildInboxInfo({ summary: '暂无可读内容', statusText: '暂无邮件' });
    }

    if (/暂无|没有|empty|not found/i.test(readableText)) {
        return buildInboxInfo({
            summary: '暂无邮件',
            copyText: readableText.slice(0, 1200),
            statusText: '暂无邮件',
        });
    }

    return buildInboxInfo({
        summary: `已取件：${readableText.slice(0, 120)}`,
        copyText: readableText.slice(0, 4000),
        messageCount: 1,
        statusText: '已取件',
    });
}

function isEmailReadableContentType(contentType) {
    const normalizedContentType = String(contentType || '').toLowerCase();
    return (
        normalizedContentType.includes('text/') ||
        normalizedContentType.includes('json') ||
        normalizedContentType.includes('html') ||
        !normalizedContentType
    );
}
