const EMAIL_ACCOUNTS_STORAGE_KEY = 'email_accounts_items_v1';
const EMAIL_FETCH_TIMEOUT_MS = 8000;
const EMAIL_FETCH_CONCURRENCY = 3;

const emailAccountBatchInput = document.getElementById('emailAccountBatchInput');
const emailAccountsFeedback = document.getElementById('emailAccountsFeedback');
const importEmailAccountsBtn = document.getElementById('importEmailAccountsBtn');
const clearEmailTextareaBtn = document.getElementById('clearEmailTextareaBtn');
const clearEmailLocalDataBtn = document.getElementById('clearEmailLocalDataBtn');
const fetchAllEmailAccountsBtn = document.getElementById('fetchAllEmailAccountsBtn');
const emailAccountsFileInput = document.getElementById('emailAccountsFileInput');
const emailAccountsGrid = document.getElementById('emailAccountsGrid');
const emailEmptyState = document.getElementById('emailEmptyState');
const emailTotalValue = document.getElementById('emailTotalValue');
const emailVisibleValue = document.getElementById('emailVisibleValue');
const emailSavedAtValue = document.getElementById('emailSavedAtValue');
const emailAccountsSearchInput = document.getElementById('emailAccountsSearchInput');
const emailInvalidLinesBox = document.getElementById('emailInvalidLinesBox');
const emailInvalidLinesList = document.getElementById('emailInvalidLinesList');

let currentEmailAccounts = Object.freeze([]);
let currentEmailInvalidLines = Object.freeze([]);
let currentEmailSavedAt = '';

function setEmailFeedback(message, tone = '') {
    emailAccountsFeedback.textContent = message;
    emailAccountsFeedback.className = 'feedback';
    if (tone) {
        emailAccountsFeedback.classList.add(`feedback--${tone}`);
    }
}

function setFetchAllButtonState(label, disabled) {
    if (!fetchAllEmailAccountsBtn) {
        return;
    }

    fetchAllEmailAccountsBtn.textContent = label;
    fetchAllEmailAccountsBtn.disabled = disabled;
}

function formatEmailSavedAt(value) {
    if (!value) {
        return '暂无';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '暂无';
    }

    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatEmailCheckedAt(value) {
    if (!value) {
        return '未取件';
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '未取件';
    }

    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function loadEmailAccountState() {
    try {
        const rawValue = window.localStorage.getItem(EMAIL_ACCOUNTS_STORAGE_KEY);
        if (!rawValue) {
            return;
        }

        const parsedValue = JSON.parse(rawValue);
        const parsedAccounts = Array.isArray(parsedValue?.accounts) ? parsedValue.accounts : [];
        currentEmailAccounts = createFrozenEmailAccounts(
            parsedAccounts.filter((account) =>
                typeof account?.email === 'string' &&
                typeof account?.sourceUrl === 'string'
            )
        );
        currentEmailSavedAt = typeof parsedValue?.savedAt === 'string' ? parsedValue.savedAt : '';
        currentEmailInvalidLines = Object.freeze([]);
    } catch (_error) {
        currentEmailAccounts = Object.freeze([]);
        currentEmailSavedAt = '';
        currentEmailInvalidLines = Object.freeze([]);
        setEmailFeedback('读取本地邮箱数据失败，已忽略旧数据。', 'warning');
    }
}

function persistEmailAccountState(accounts) {
    const savedAt = new Date().toISOString();
    const storagePayload = {
        savedAt,
        accounts: accounts.map((account) => ({
            sequence: account.sequence,
            email: account.email,
            sourceUrl: account.sourceUrl,
            displayUrl: account.displayUrl,
            sourceName: account.sourceName,
            uid: account.uid,
            password: account.password,
            uiUrl: account.uiUrl,
            apiUrl: account.apiUrl,
            host: account.host,
            statusText: account.statusText,
            inbox: account.inbox,
        })),
    };

    window.localStorage.setItem(EMAIL_ACCOUNTS_STORAGE_KEY, JSON.stringify(storagePayload));
    currentEmailAccounts = createFrozenEmailAccounts(accounts);
    currentEmailSavedAt = savedAt;
}

function clearEmailAccountState() {
    window.localStorage.removeItem(EMAIL_ACCOUNTS_STORAGE_KEY);
    currentEmailAccounts = Object.freeze([]);
    currentEmailInvalidLines = Object.freeze([]);
    currentEmailSavedAt = '';
}

async function copyEmailText(text) {
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

function renderEmailInvalidLines(invalidLines) {
    emailInvalidLinesList.innerHTML = '';

    if (!invalidLines.length) {
        emailInvalidLinesBox.hidden = true;
        return;
    }

    invalidLines.forEach((item) => {
        const line = document.createElement('li');
        line.textContent = `第 ${item.lineNumber} 行：${item.reason}`;
        emailInvalidLinesList.appendChild(line);
    });

    emailInvalidLinesBox.hidden = false;
}

function createEmailButton(className, text, title, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = text;
    button.title = title;
    button.addEventListener('click', onClick);
    return button;
}

function createEmailMetaLine(label, value) {
    const line = document.createElement('div');
    line.className = 'email-account-card__meta';
    line.textContent = `${label}：${value}`;
    return line;
}

function buildEmailSearchText(account) {
    return [
        account.email,
        account.sourceUrl,
        account.displayUrl,
        account.sourceName,
        account.uid,
        account.host,
        account.apiUrl,
        account.uiUrl,
        account.statusText,
        account.inbox.summary,
        account.inbox.copyText,
    ].join(' ').toLowerCase();
}

function getStatusClass(account) {
    if (account.inbox.messageCount > 0) {
        return 'email-account-card__status email-account-card__status--success';
    }

    if (account.statusText.includes('失败') || account.statusText.includes('暂无')) {
        return 'email-account-card__status email-account-card__status--warning';
    }

    return 'email-account-card__status';
}

function renderEmailAccounts() {
    const keyword = (emailAccountsSearchInput.value || '').trim().toLowerCase();
    const filteredAccounts = currentEmailAccounts.filter((account) => !keyword || buildEmailSearchText(account).includes(keyword));

    emailAccountsGrid.innerHTML = '';
    emailTotalValue.textContent = String(currentEmailAccounts.length);
    emailVisibleValue.textContent = String(filteredAccounts.length);
    emailSavedAtValue.textContent = formatEmailSavedAt(currentEmailSavedAt);
    renderEmailInvalidLines(currentEmailInvalidLines);

    if (!currentEmailAccounts.length) {
        emailEmptyState.hidden = false;
        emailAccountsGrid.hidden = true;
        return;
    }

    emailEmptyState.hidden = true;
    emailAccountsGrid.hidden = false;

    filteredAccounts.forEach((account) => {
        const accountIndex = currentEmailAccounts.findIndex((currentAccount) => currentAccount === account);
        const card = document.createElement('article');
        card.className = 'email-account-card';
        card.title = `邮箱：${account.email}\n状态：${account.statusText}\n来源：${account.displayUrl}`;

        const main = document.createElement('div');
        main.className = 'email-account-card__main';

        const title = document.createElement('div');
        title.className = 'email-account-card__title';

        const email = document.createElement('div');
        email.className = 'email-account-card__email';
        email.textContent = account.email;

        const source = document.createElement('div');
        source.className = 'email-account-card__source';
        source.textContent = account.sourceName ? `${account.host} · ${account.sourceName}` : account.displayUrl;
        title.append(email, source);

        const status = document.createElement('span');
        status.className = getStatusClass(account);
        status.textContent = account.statusText || '待取件';
        main.append(title, status);

        const actions = document.createElement('div');
        actions.className = 'email-account-card__actions';

        const copyButton = createEmailButton('btn btn-primary', '复制邮箱', `复制邮箱：${account.email}`, async () => {
            await copyEmailText(account.email);
            setEmailFeedback(`已复制邮箱：${account.email}`, 'success');
        });

        const fetchButton = createEmailButton('btn btn-secondary', '取件', `读取邮箱：${account.email}`, async () => {
            fetchButton.disabled = true;
            fetchButton.textContent = '取件中';
            await fetchSingleEmailAccount(accountIndex);
        });

        const openButton = createEmailButton('btn btn-secondary', '打开', `打开取件网址：${account.displayUrl}`, () => {
            window.open(account.sourceUrl, '_blank', 'noopener,noreferrer');
        });

        actions.append(copyButton, fetchButton, openButton);

        const links = document.createElement('div');
        links.className = 'email-account-card__links';

        const copySourceButton = createEmailButton('btn btn-secondary', '复制取件链接', '复制原始取件链接', async () => {
            await copyEmailText(account.sourceUrl);
            setEmailFeedback(`已复制取件链接：${account.email}`, 'success');
        });
        links.appendChild(copySourceButton);

        if (account.apiUrl) {
            links.appendChild(createEmailButton('btn btn-secondary', '复制 API', '复制读信 JSON API', async () => {
                await copyEmailText(account.apiUrl);
                setEmailFeedback(`已复制 API：${account.email}`, 'success');
            }));
        }

        if (account.uiUrl) {
            links.appendChild(createEmailButton('btn btn-secondary', '打开邮箱 UI', '打开免登录邮箱 UI', () => {
                window.open(account.uiUrl, '_blank', 'noopener,noreferrer');
            }));
        }

        const checkedLine = createEmailMetaLine('最近取件', formatEmailCheckedAt(account.inbox.checkedAt));
        const uidLine = createEmailMetaLine('UID', account.uid || '未提供');
        const passLine = createEmailMetaLine('密码', account.password ? '已识别' : '未识别');

        const result = document.createElement('pre');
        result.className = 'email-account-card__result';
        result.textContent = account.inbox.copyText || account.inbox.summary || '';

        card.append(main, actions, links, checkedLine, uidLine, passLine, result);
        emailAccountsGrid.appendChild(card);
    });
}

async function fetchEmailPageDirect(openUrl) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), EMAIL_FETCH_TIMEOUT_MS);

    try {
        const response = await fetch(openUrl, {
            method: 'GET',
            mode: 'cors',
            cache: 'no-store',
            signal: controller.signal,
            headers: {
                Accept: 'application/json,text/html,text/plain;q=0.9,*/*;q=0.8',
            },
        });
        const contentType = response.headers.get('content-type') || '';
        const rawText = isEmailReadableContentType(contentType) ? await response.text() : '';

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

async function fetchEmailPageViaServer(openUrl) {
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

async function fetchEmailPageContent(openUrl) {
    try {
        return await fetchEmailPageDirect(openUrl);
    } catch (_directError) {
        return await fetchEmailPageViaServer(openUrl);
    }
}

function dedupeEmailAccounts(accounts) {
    return createFrozenEmailAccounts(accounts.reduce((result, account) => {
        const key = `${account.email.toLowerCase()}|${account.password}|${account.apiUrl || account.sourceUrl}`;
        if (result.keys.includes(key)) {
            return result;
        }

        return {
            keys: result.keys.concat([key]),
            accounts: result.accounts.concat([account]),
        };
    }, { keys: [], accounts: [] }).accounts);
}

async function discoverAccountsForSourceLink(sourceLink) {
    const pageContent = await fetchEmailPageContent(sourceLink.sourceUrl);
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

async function expandEmailAccountImportResult(parsed) {
    const sourceLinks = Array.isArray(parsed.sourceLinks) ? parsed.sourceLinks : [];
    const discoveryResults = await Promise.all(sourceLinks.map(async (sourceLink) => {
        try {
            const accounts = await discoverAccountsForSourceLink(sourceLink);
            return Object.freeze({ accounts, invalidLines: [] });
        } catch (error) {
            const reason = error.message === 'missing-email-password'
                ? '入口链接未识别到邮箱和密码'
                : `入口链接读取失败：${error.message}`;
            return Object.freeze({
                accounts: [],
                invalidLines: [{ lineNumber: sourceLink.lineNumber || sourceLink.sequence, reason }],
            });
        }
    }));

    const discoveredAccounts = discoveryResults.flatMap((result) => result.accounts);
    const discoveryInvalidLines = discoveryResults.flatMap((result) => result.invalidLines);

    return Object.freeze({
        accounts: dedupeEmailAccounts(parsed.accounts.concat(discoveredAccounts)),
        invalidLines: Object.freeze(parsed.invalidLines.concat(discoveryInvalidLines)),
    });
}

function mergeAccountDiscovery(account, discovery) {
    return Object.freeze({
        ...account,
        email: discovery.email || account.email,
        password: discovery.password || account.password,
        uid: discovery.uid || account.uid,
        sourceName: discovery.sourceName || account.sourceName,
        host: discovery.host || account.host,
        uiUrl: discovery.uiUrl || account.uiUrl,
        apiUrl: discovery.apiUrl || account.apiUrl,
    });
}

async function fetchInboxForEmailAccount(account) {
    const checkedAt = new Date().toISOString();
    const primaryUrl = account.apiUrl || account.sourceUrl;
    const primaryContent = await fetchEmailPageContent(primaryUrl);
    const primaryDiscovery = discoverEmailApiLinks(primaryContent.rawText, primaryContent.contentType, primaryUrl, account);
    const discoveredAccount = mergeAccountDiscovery(account, primaryDiscovery);

    if (!primaryContent.ok) {
        return Object.freeze({
            ...discoveredAccount,
            statusText: `取件失败 HTTP ${primaryContent.status}`,
            inbox: buildInboxInfo({
                summary: `取件失败 HTTP ${primaryContent.status}`,
                checkedAt,
                statusText: '取件失败',
            }),
        });
    }

    const shouldFetchDiscoveredApi = discoveredAccount.apiUrl && discoveredAccount.apiUrl !== primaryUrl;
    const inboxContent = shouldFetchDiscoveredApi
        ? await fetchEmailPageContent(discoveredAccount.apiUrl)
        : primaryContent;
    const inboxDiscovery = discoverEmailApiLinks(inboxContent.rawText, inboxContent.contentType, discoveredAccount.apiUrl || primaryUrl, discoveredAccount);
    const finalAccount = mergeAccountDiscovery(discoveredAccount, inboxDiscovery);
    const parsedInbox = parseInboxContent(inboxContent.rawText, inboxContent.contentType);

    return Object.freeze({
        ...finalAccount,
        statusText: parsedInbox.statusText || '已取件',
        inbox: buildInboxInfo({
            ...parsedInbox,
            checkedAt,
        }),
    });
}

async function fetchSingleEmailAccount(accountIndex) {
    const targetAccount = currentEmailAccounts[accountIndex];
    if (!targetAccount) {
        setEmailFeedback('没有找到要取件的邮箱。', 'warning');
        renderEmailAccounts();
        return;
    }

    try {
        const fetchedAccount = await fetchInboxForEmailAccount(targetAccount);
        const nextAccounts = createFrozenEmailAccounts(
            currentEmailAccounts.map((account, index) => (
                index === accountIndex ? fetchedAccount : account
            ))
        );
        persistEmailAccountState(nextAccounts);
        renderEmailAccounts();
        setEmailFeedback(`已取件：${fetchedAccount.email}`, fetchedAccount.inbox.messageCount > 0 ? 'success' : 'warning');
    } catch (error) {
        const checkedAt = new Date().toISOString();
        const failedAccounts = createFrozenEmailAccounts(
            currentEmailAccounts.map((account, index) => (
                index === accountIndex
                    ? Object.freeze({
                        ...account,
                        statusText: error?.name === 'AbortError' ? '取件超时' : '取件失败',
                        inbox: buildInboxInfo({
                            summary: error?.name === 'AbortError' ? '取件超时' : '目标站点限制读取或接口异常',
                            checkedAt,
                            statusText: '取件失败',
                        }),
                    })
                    : account
            ))
        );
        persistEmailAccountState(failedAccounts);
        renderEmailAccounts();
        setEmailFeedback(`取件失败：${targetAccount.email}`, 'error');
    }
}

async function fetchAllEmailAccounts() {
    if (!currentEmailAccounts.length) {
        setEmailFeedback('当前没有可取件的邮箱。', 'warning');
        return;
    }

    setFetchAllButtonState(`取件中 0/${currentEmailAccounts.length}`, true);

    let cursor = 0;
    let completed = 0;
    const fetchedAccounts = new Array(currentEmailAccounts.length);

    const worker = async () => {
        while (cursor < currentEmailAccounts.length) {
            const index = cursor;
            cursor += 1;
            const account = currentEmailAccounts[index];
            try {
                fetchedAccounts[index] = await fetchInboxForEmailAccount(account);
            } catch (error) {
                fetchedAccounts[index] = Object.freeze({
                    ...account,
                    statusText: error?.name === 'AbortError' ? '取件超时' : '取件失败',
                    inbox: buildInboxInfo({
                        summary: error?.name === 'AbortError' ? '取件超时' : '目标站点限制读取或接口异常',
                        checkedAt: new Date().toISOString(),
                        statusText: '取件失败',
                    }),
                });
            }
            completed += 1;
            setFetchAllButtonState(`取件中 ${completed}/${currentEmailAccounts.length}`, true);
        }
    };

    const workers = Array.from(
        { length: Math.min(EMAIL_FETCH_CONCURRENCY, currentEmailAccounts.length) },
        () => worker()
    );
    await Promise.all(workers);

    const nextAccounts = createFrozenEmailAccounts(fetchedAccounts);
    persistEmailAccountState(nextAccounts);
    renderEmailAccounts();
    setFetchAllButtonState('取件全部', false);
    setEmailFeedback(`已完成 ${nextAccounts.length} 个邮箱取件。`, 'success');
}

async function importEmailAccountsFromTextarea() {
    const content = emailAccountBatchInput.value.trim();
    if (!content) {
        setEmailFeedback('请先粘贴取件网址或导入 txt 文件。', 'warning');
        return;
    }

    const parsed = parseEmailAccountBatch(content);
    const hasSourceLinks = Boolean(parsed.sourceLinks && parsed.sourceLinks.length);
    importEmailAccountsBtn.disabled = true;
    importEmailAccountsBtn.textContent = hasSourceLinks ? '读取入口中' : '解析中';
    setEmailFeedback(hasSourceLinks ? '正在读取入口链接并识别邮箱密码…' : '正在解析邮箱账户…', 'warning');

    try {
        const expanded = await expandEmailAccountImportResult(parsed);
        currentEmailInvalidLines = expanded.invalidLines;

        if (!expanded.accounts.length) {
            currentEmailAccounts = Object.freeze([]);
            currentEmailSavedAt = '';
            renderEmailAccounts();
            setEmailFeedback('没有解析出有效邮箱，请检查入口链接是否可读取且包含邮箱密码。', 'error');
            return;
        }

        persistEmailAccountState(expanded.accounts);
        renderEmailAccounts();

        const message = expanded.invalidLines.length
            ? `已保存 ${expanded.accounts.length} 个邮箱，另有 ${expanded.invalidLines.length} 行未导入。`
            : `已保存 ${expanded.accounts.length} 个邮箱到浏览器本地。`;
        setEmailFeedback(message, expanded.invalidLines.length ? 'warning' : 'success');
    } finally {
        importEmailAccountsBtn.disabled = false;
        importEmailAccountsBtn.textContent = '解析并保存到本地';
    }
}

async function handleEmailFileImport(file) {
    if (!file) {
        return;
    }

    const textContent = await file.text();
    emailAccountBatchInput.value = textContent;
    setEmailFeedback(`已读取文件：${file.name}，请确认后点击“解析并保存到本地”。`, 'success');
}

importEmailAccountsBtn.addEventListener('click', importEmailAccountsFromTextarea);

clearEmailTextareaBtn.addEventListener('click', () => {
    emailAccountBatchInput.value = '';
    setEmailFeedback('已清空输入框。', 'success');
});

clearEmailLocalDataBtn.addEventListener('click', () => {
    if (!window.confirm || window.confirm('确认清空当前浏览器保存的邮箱账户吗？')) {
        clearEmailAccountState();
        renderEmailAccounts();
        setEmailFeedback('已清空本地邮箱账户。', 'success');
    }
});

fetchAllEmailAccountsBtn.addEventListener('click', fetchAllEmailAccounts);

emailAccountsFileInput.addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    handleEmailFileImport(file);
    event.target.value = '';
});

emailAccountsSearchInput.addEventListener('input', renderEmailAccounts);

loadEmailAccountState();
renderEmailAccounts();
