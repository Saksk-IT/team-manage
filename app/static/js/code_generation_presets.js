/**
 * 兑换码生成预设
 * 管理系统内置预设与浏览器本地自定义预设。
 */
const CODE_GENERATION_PRESET_STORAGE_KEY = 'team_manage_code_generation_presets_v1';
const CODE_GENERATION_PRESET_MAX_CUSTOM = 12;
const CODE_GENERATION_PRESET_NAME_MAX_LENGTH = 20;
const CODE_GENERATION_PRESET_LIMITS = Object.freeze({
    expiresDays: { min: 1, max: 3650 },
    warrantyDays: { min: 1, max: 3650 },
    warrantyClaims: { min: 0, max: 1000 },
    warrantySeconds: { min: 3600, max: 3650 * 86400 }
});
const DEFAULT_CODE_GENERATION_PRESETS = Object.freeze([]);

function normalizeCodePresetName(name) {
    return String(name || '').trim().replace(/\s+/g, ' ');
}

function parseCodePresetInteger(value, key, allowNull = false) {
    if (value === null || value === undefined || String(value).trim() === '') {
        return allowNull ? null : undefined;
    }

    const parsed = Number.parseInt(value, 10);
    const limit = CODE_GENERATION_PRESET_LIMITS[key];
    if (!Number.isInteger(parsed) || !limit || parsed < limit.min || parsed > limit.max) {
        return undefined;
    }

    return parsed;
}

function calculateCodeGenerationDaysFromSeconds(totalSeconds) {
    if (totalSeconds === null || totalSeconds === undefined) {
        return undefined;
    }

    const safeSeconds = Math.max(Math.floor(Number(totalSeconds) || 0), 0);
    return Math.max(Math.ceil(safeSeconds / 86400), 1);
}

function parseCodePresetSeconds(value) {
    if (value === null || value === undefined || String(value).trim() === '') {
        return undefined;
    }

    const parsed = Number.parseInt(value, 10);
    const limit = CODE_GENERATION_PRESET_LIMITS.warrantySeconds;
    if (!Number.isInteger(parsed) || parsed < limit.min || parsed > limit.max) {
        return undefined;
    }

    return parsed;
}

function resolveRawCodePresetWarrantySeconds(rawPreset) {
    const warrantySeconds = parseCodePresetSeconds(rawPreset?.warrantySeconds);
    if (warrantySeconds !== undefined) {
        return warrantySeconds;
    }

    const warrantyDays = parseCodePresetInteger(rawPreset?.warrantyDays, 'warrantyDays');
    if (warrantyDays === undefined) {
        return undefined;
    }

    return warrantyDays * 86400;
}

function normalizeCodeGenerationPreset(rawPreset, builtIn = false) {
    const name = normalizeCodePresetName(rawPreset?.name);
    const expiresDays = parseCodePresetInteger(rawPreset?.expiresDays, 'expiresDays', true);
    const warrantySeconds = resolveRawCodePresetWarrantySeconds(rawPreset);
    const warrantyDays = parseCodePresetInteger(rawPreset?.warrantyDays, 'warrantyDays')
        ?? calculateCodeGenerationDaysFromSeconds(warrantySeconds);
    const warrantyClaims = parseCodePresetInteger(rawPreset?.warrantyClaims, 'warrantyClaims');

    if (!name || name.length > CODE_GENERATION_PRESET_NAME_MAX_LENGTH) {
        return null;
    }

    if (expiresDays === undefined || warrantySeconds === undefined || warrantyDays === undefined || warrantyClaims === undefined) {
        return null;
    }

    return {
        id: String(rawPreset?.id || `custom-${Date.now()}`),
        name,
        expiresDays,
        warrantyDays,
        warrantySeconds,
        warrantyClaims,
        builtIn: Boolean(builtIn || rawPreset?.builtIn)
    };
}

function getDefaultCodeGenerationPresets() {
    return DEFAULT_CODE_GENERATION_PRESETS
        .map((preset) => normalizeCodeGenerationPreset(preset, true))
        .filter(Boolean);
}

function getCustomCodeGenerationPresets() {
    try {
        const savedPresets = JSON.parse(localStorage.getItem(CODE_GENERATION_PRESET_STORAGE_KEY) || '[]');
        if (!Array.isArray(savedPresets)) {
            return [];
        }

        return savedPresets
            .map((preset) => normalizeCodeGenerationPreset(preset, false))
            .filter(Boolean)
            .slice(0, CODE_GENERATION_PRESET_MAX_CUSTOM);
    } catch (error) {
        console.warn('读取兑换码生成预设失败:', error);
        return [];
    }
}

function saveCustomCodeGenerationPresets(presets) {
    try {
        const normalizedPresets = presets
            .map((preset) => normalizeCodeGenerationPreset(preset, false))
            .filter(Boolean)
            .slice(0, CODE_GENERATION_PRESET_MAX_CUSTOM)
            .map(({ id, name, expiresDays, warrantyDays, warrantySeconds, warrantyClaims }) => ({
                id,
                name,
                expiresDays,
                warrantyDays,
                warrantySeconds,
                warrantyClaims
            }));

        localStorage.setItem(CODE_GENERATION_PRESET_STORAGE_KEY, JSON.stringify(normalizedPresets));
        return true;
    } catch (error) {
        console.error('保存兑换码生成预设失败:', error);
        showToast('保存预设失败，请检查浏览器存储权限', 'error');
        return false;
    }
}

function getAllCodeGenerationPresets() {
    return [
        ...getDefaultCodeGenerationPresets(),
        ...getCustomCodeGenerationPresets()
    ];
}

function findCodeGenerationPreset(presetId) {
    return getAllCodeGenerationPresets().find((preset) => preset.id === presetId) || null;
}

function formatCodeGenerationPresetMeta(preset) {
    const expiresText = preset.expiresDays ? `${preset.expiresDays}天` : '永久';
    return `有效期 ${expiresText} · 质保 ${formatCodeGenerationDuration(preset.warrantySeconds)} · ${preset.warrantyClaims}次`;
}

function formatCodeGenerationDuration(totalSeconds) {
    const safeSeconds = Math.max(Math.floor(Number(totalSeconds) || 0), 0);
    const days = Math.floor(safeSeconds / 86400);
    const hours = Math.floor((safeSeconds % 86400) / 3600);

    if (days > 0 && hours > 0) {
        return `${days}天${hours}小时`;
    }
    if (days > 0) {
        return `${days}天`;
    }
    return `${hours}小时`;
}

function setCodeGenerationWarrantyDuration(form, totalSeconds) {
    const safeSeconds = Math.max(Math.floor(Number(totalSeconds) || 0), 0);
    const days = Math.floor(safeSeconds / 86400);
    const hours = Math.floor((safeSeconds % 86400) / 3600);

    setCodeGenerationFormInputValue(form, 'warrantyDays', days);
    setCodeGenerationFormInputValue(form, 'warrantyHours', hours);
}

function parseCodeGenerationWarrantyDuration(form) {
    const rawDays = form.querySelector('[name="warrantyDays"]')?.value ?? '';
    const rawHours = form.querySelector('[name="warrantyHours"]')?.value ?? '';
    const days = rawDays === '' ? 0 : Number(rawDays);
    const hours = rawHours === '' ? 0 : Number(rawHours);

    if (!Number.isInteger(days) || days < 0 || days > 3650) {
        return { error: '质保剩余天数必须为 0-3650 的整数' };
    }
    if (!Number.isInteger(hours) || hours < 0 || hours > 23) {
        return { error: '质保剩余小时必须为 0-23 的整数' };
    }

    const seconds = days * 86400 + hours * 3600;
    if (seconds < CODE_GENERATION_PRESET_LIMITS.warrantySeconds.min) {
        return { error: '质保剩余时间至少为 1 小时' };
    }

    return { seconds, days: calculateCodeGenerationDaysFromSeconds(seconds) };
}

function createCodeGenerationPresetApplyButton(preset) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'quick-value-btn code-preset-apply-btn';
    button.dataset.presetId = preset.id;
    button.setAttribute('aria-label', `应用${preset.name}预设`);
    button.addEventListener('click', () => applyCodeGenerationPreset(button, preset.id));

    const name = document.createElement('span');
    name.className = 'code-preset-name';
    name.textContent = preset.name;

    const meta = document.createElement('span');
    meta.className = 'code-preset-meta';
    meta.textContent = formatCodeGenerationPresetMeta(preset);

    button.append(name, meta);
    return button;
}

function createCodeGenerationPresetDeleteButton(preset) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'code-preset-delete-btn';
    button.textContent = '删除';
    button.setAttribute('aria-label', `删除${preset.name}预设`);
    button.addEventListener('click', () => deleteCodeGenerationPreset(button, preset.id));
    return button;
}

function renderCodeGenerationPresets() {
    const presetLists = document.querySelectorAll('[data-code-preset-list]');
    if (!presetLists.length) {
        return;
    }

    const presets = getAllCodeGenerationPresets();
    presetLists.forEach((list) => {
        list.innerHTML = '';
        if (!presets.length) {
            const empty = document.createElement('div');
            empty.className = 'code-preset-empty';
            empty.textContent = '暂无自定义预设，可填写下方配置后保存。';
            list.appendChild(empty);
            return;
        }

        presets.forEach((preset) => {
            const item = document.createElement('div');
            item.className = 'code-preset-item';
            item.appendChild(createCodeGenerationPresetApplyButton(preset));
            if (!preset.builtIn) {
                item.appendChild(createCodeGenerationPresetDeleteButton(preset));
            }
            list.appendChild(item);
        });
    });
}

function getCodeGenerationPresetContext(control) {
    const panel = control?.closest?.('.code-preset-panel');
    const form = control?.closest?.('form');
    if (!panel || !form) {
        return null;
    }

    return {
        panel,
        form,
        scope: panel.dataset.codePresetScope || ''
    };
}

function setCodeGenerationFormInputValue(form, name, value) {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) {
        return;
    }

    input.value = value === null || value === undefined ? '' : String(value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

function syncQuickNumberButtons(form) {
    form.querySelectorAll('.quick-value-row').forEach((row) => {
        const group = row.closest('.form-group');
        const firstButton = row.querySelector('.quick-value-btn');
        const onclickValue = firstButton?.getAttribute?.('onclick') || '';
        const durationMatch = onclickValue.match(/setQuickWarrantyDuration\([^,]+,\s*(\d+)\s*,\s*(\d+)/);
        if (durationMatch) {
            const daysInput = group?.querySelector?.('input[name="warrantyDays"]');
            const hoursInput = group?.querySelector?.('input[name="warrantyHours"]');
            const currentDays = Number.parseInt(daysInput?.value || '0', 10);
            const currentHours = Number.parseInt(hoursInput?.value || '0', 10);
            row.querySelectorAll('.quick-value-btn').forEach((button) => {
                const buttonMatch = button.getAttribute('onclick')?.match(/setQuickWarrantyDuration\([^,]+,\s*(\d+)\s*,\s*(\d+)/);
                const buttonDays = Number.parseInt(buttonMatch?.[1] || '', 10);
                const buttonHours = Number.parseInt(buttonMatch?.[2] || '', 10);
                button.classList.toggle(
                    'active',
                    Number.isInteger(currentDays)
                    && Number.isInteger(currentHours)
                    && buttonDays === currentDays
                    && buttonHours === currentHours
                );
            });
            return;
        }

        const targetMatch = onclickValue.match(/setQuickNumberValue\([^,]+,\s*'([^']+)'/);
        const targetName = targetMatch?.[1] || '';
        const input = targetName
            ? group?.querySelector?.(`input[name="${targetName}"], input[data-quick-target="${targetName}"]`)
            : null;
        if (!input) {
            return;
        }

        const currentValue = Number.parseInt(input.value, 10);
        row.querySelectorAll('.quick-value-btn').forEach((button) => {
            const buttonValue = Number.parseInt(button.textContent, 10);
            button.classList.toggle(
                'active',
                Number.isInteger(currentValue) && buttonValue === currentValue
            );
        });
    });
}

function applyCodeGenerationPreset(control, presetId) {
    const context = getCodeGenerationPresetContext(control);
    const preset = findCodeGenerationPreset(presetId);
    if (!context || !preset) {
        showToast('预设不存在或已被删除', 'error');
        renderCodeGenerationPresets();
        return;
    }

    setCodeGenerationFormInputValue(context.form, 'expiresDays', preset.expiresDays);
    setCodeGenerationWarrantyDuration(context.form, preset.warrantySeconds);
    setCodeGenerationFormInputValue(context.form, 'warrantyClaims', preset.warrantyClaims);

    const warrantyCheckbox = context.form.querySelector('input[name="hasWarranty"]');
    if (warrantyCheckbox) {
        warrantyCheckbox.checked = true;
        toggleWarrantyDays(warrantyCheckbox, `${context.scope}-warranty-days-group`);
    }

    syncQuickNumberButtons(context.form);
    showToast(`已应用预设：${preset.name}`, 'success');
}

function readCodeGenerationPresetFormValues(form) {
    const expiresInput = form.querySelector('[name="expiresDays"]')?.value || '';
    const warrantyClaimsInput = form.querySelector('[name="warrantyClaims"]')?.value || '';
    const expiresDays = parseCodePresetInteger(expiresInput, 'expiresDays', true);
    const warrantyDuration = parseCodeGenerationWarrantyDuration(form);
    const warrantyClaims = parseCodePresetInteger(warrantyClaimsInput, 'warrantyClaims');

    if (expiresDays === undefined) {
        return { error: '有效期必须为 1-3650 天，留空表示永久有效' };
    }
    if (warrantyDuration.error) {
        return { error: warrantyDuration.error };
    }
    if (warrantyClaims === undefined) {
        return { error: '质保次数必须为 0-1000 次' };
    }

    return {
        expiresDays,
        warrantyDays: warrantyDuration.days,
        warrantySeconds: warrantyDuration.seconds,
        warrantyClaims
    };
}

function createCustomCodeGenerationPresetId() {
    const randomPart = Math.random().toString(36).slice(2, 8);
    return `custom-${Date.now()}-${randomPart}`;
}

function saveCodeGenerationPreset(control) {
    const context = getCodeGenerationPresetContext(control);
    if (!context) {
        showToast('未找到生成表单，无法保存预设', 'error');
        return;
    }

    const nameInput = context.form.querySelector('[name="presetName"]');
    const name = normalizeCodePresetName(nameInput?.value);
    if (!name) {
        showToast('请先填写预设名称', 'error');
        nameInput?.focus();
        return;
    }
    if (name.length > CODE_GENERATION_PRESET_NAME_MAX_LENGTH) {
        showToast(`预设名称不能超过 ${CODE_GENERATION_PRESET_NAME_MAX_LENGTH} 个字符`, 'error');
        nameInput?.focus();
        return;
    }

    const formValues = readCodeGenerationPresetFormValues(context.form);
    if (formValues.error) {
        showToast(formValues.error, 'error');
        return;
    }

    const normalizedName = name.toLowerCase();
    const defaultNameExists = getDefaultCodeGenerationPresets()
        .some((preset) => preset.name.toLowerCase() === normalizedName);
    if (defaultNameExists) {
        showToast('预设名称已被系统预设使用，请换一个名称', 'error');
        nameInput?.focus();
        return;
    }

    const customPresets = getCustomCodeGenerationPresets();
    const existingPreset = customPresets.find((preset) => preset.name.toLowerCase() === normalizedName);
    if (!existingPreset && customPresets.length >= CODE_GENERATION_PRESET_MAX_CUSTOM) {
        showToast(`最多保存 ${CODE_GENERATION_PRESET_MAX_CUSTOM} 个自定义预设`, 'error');
        return;
    }

    const nextPreset = {
        id: existingPreset?.id || createCustomCodeGenerationPresetId(),
        name,
        expiresDays: formValues.expiresDays,
        warrantyDays: formValues.warrantyDays,
        warrantySeconds: formValues.warrantySeconds,
        warrantyClaims: formValues.warrantyClaims
    };
    const nextPresets = existingPreset
        ? customPresets.map((preset) => preset.id === existingPreset.id ? nextPreset : preset)
        : [...customPresets, nextPreset];

    if (!saveCustomCodeGenerationPresets(nextPresets)) {
        return;
    }

    if (nameInput) {
        nameInput.value = '';
    }
    renderCodeGenerationPresets();
    showToast(existingPreset ? '预设已更新' : '预设已保存', 'success');
}

async function deleteCodeGenerationPreset(control, presetId) {
    const preset = findCodeGenerationPreset(presetId);
    if (!preset || preset.builtIn) {
        showToast('系统预设不能删除', 'error');
        return;
    }

    const confirmed = await showSystemConfirm({
        title: '删除自定义预设',
        message: `确定要删除“${preset.name}”吗？`,
        confirmText: '删除',
        danger: true,
    });
    if (!confirmed) {
        return;
    }

    const customPresets = getCustomCodeGenerationPresets();
    const nextPresets = customPresets.filter((customPreset) => customPreset.id !== presetId);
    if (nextPresets.length === customPresets.length) {
        showToast('预设不存在或已被删除', 'error');
        renderCodeGenerationPresets();
        return;
    }

    if (saveCustomCodeGenerationPresets(nextPresets)) {
        renderCodeGenerationPresets();
        showToast('预设已删除', 'success');
    }
}

function resetCodeGenerationForm(form, warrantyGroupId) {
    if (!form) {
        return;
    }

    const warrantyCheckbox = form.querySelector('input[name="hasWarranty"]');
    if (warrantyCheckbox) {
        toggleWarrantyDays(warrantyCheckbox, warrantyGroupId);
    }

    const presetNameInput = form.querySelector('[name="presetName"]');
    if (presetNameInput) {
        presetNameInput.value = '';
    }

    syncQuickNumberButtons(form);
}

function initCodeGenerationPresets() {
    renderCodeGenerationPresets();
}


document.addEventListener('DOMContentLoaded', initCodeGenerationPresets);
