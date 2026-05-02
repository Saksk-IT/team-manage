"""前台质保邮箱核查的独立静态教程内容。"""
from __future__ import annotations

from html import escape
from typing import Iterable


STATIC_TUTORIAL_TITLE = "兑换中转 API Key，并接入 Codex"
STATIC_TUTORIAL_SUBTITLE = "这是前台邮箱核查结果中直接展示的固定教程内容，已按当前页面重新排版。"
STATIC_TUTORIAL_MESSAGE = "已展示固定教程页面，请按下方步骤继续。"


def _build_step_card(
    index: int,
    title: str,
    tag: str,
    description: str,
    bullets: Iterable[str],
    link_text: str = "",
    link_url: str = "",
) -> str:
    bullet_items = "".join(
        f"<li>{escape(str(item))}</li>"
        for item in bullets
        if str(item).strip()
    )
    link_html = ""
    if link_text and link_url:
        link_html = (
            f'<a class="warranty-static-tutorial__step-link" href="{escape(link_url)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'<i data-lucide="external-link"></i><span>{escape(link_text)}</span></a>'
        )

    return f"""
        <article class="warranty-static-tutorial__step">
            <div class="warranty-static-tutorial__step-head">
                <div>
                    <div class="warranty-static-tutorial__step-index">{index:02d}</div>
                    <h4>{escape(title)}</h4>
                </div>
                <span class="warranty-static-tutorial__step-tag">{escape(tag)}</span>
            </div>
            <p>{escape(description)}</p>
            <ul class="warranty-static-tutorial__step-list">{bullet_items}</ul>
            {link_html}
        </article>
    """.strip()


def build_warranty_email_check_static_tutorial_message(matched: bool) -> str:
    prefix = "邮箱已通过核查" if matched else "邮箱未命中名单"
    return f"{prefix}，{STATIC_TUTORIAL_MESSAGE}"


def _build_static_tutorial_steps() -> list[str]:
    return [
        _build_step_card(
            1,
            "注册中转账户",
            "准备账号",
            "先打开中转注册页，创建属于你自己的中转账户。",
            [
                "访问注册页后，随意输入邮箱和密码即可完成创建。",
                "后续兑换与创建密钥都使用这个中转账户。",
            ],
            "打开中转注册页",
            "https://api.sakms.top/register",
        ),
        _build_step_card(
            2,
            "兑换中转码",
            "完成兑换",
            "登录后进入兑换页面，把拿到的兑换码填进去。",
            [
                "中转兑换码或额度包兑换码都在这里完成兑换。",
                "兑换成功后，再继续创建 API Key。",
            ],
        ),
        _build_step_card(
            3,
            "创建 API Key",
            "生成密钥",
            "在 API 密钥页面新建密钥，并按兑换码来源选择对应分组。",
            [
                "质保补发的中转码选择“质保补偿”。",
                "链动小铺购买的额度包选择“GPT-Plus”。",
            ],
        ),
        _build_step_card(
            4,
            "配置 Codex 文件",
            "接入客户端",
            "下载 Codex 后，把页面给出的内容分别写入本地配置文件。",
            [
                "先完全关闭正在运行的 Codex，再编辑配置。",
                "Windows 使用 %userprofile%\\.codex，Mac 使用 ~/.codex。",
                "分别把内容写入 config.toml 和 auth.json。",
            ],
            "打开 Codex 下载页",
            "https://openai.com/zh-Hans-CN/codex/",
        ),
    ]


def _build_static_tutorial_hero(matched: bool) -> str:
    status_text = "邮箱已通过核查" if matched else "邮箱未命中名单"
    status_hint = "可直接按下方步骤完成接入" if matched else "仍可继续查看固定教程"

    return f"""
        <section class="warranty-static-tutorial__hero">
            <div class="warranty-static-tutorial__eyebrow">STATIC TUTORIAL</div>
            <h3>{STATIC_TUTORIAL_TITLE}</h3>
            <p>{STATIC_TUTORIAL_SUBTITLE}</p>
            <div class="warranty-static-tutorial__badges">
                <span class="spots-badge spots-badge--success">
                    <i data-lucide="shield-check"></i>
                    <span>{status_text}</span>
                </span>
                <span class="spots-badge">
                    <i data-lucide="layout-grid"></i>
                    <span>固定写死内容</span>
                </span>
                <span class="spots-badge">
                    <i data-lucide="sparkles"></i>
                    <span>独立静态排版</span>
                </span>
            </div>
            <p class="warranty-static-tutorial__lead">{status_hint}，无需切换到其他教程页。</p>
        </section>
    """.strip()


def _build_static_tutorial_note() -> str:
    return f"""
        <section class="warranty-static-tutorial__note">
            <div class="codex-alert codex-alert--warning">
                <i data-lucide="badge-alert"></i>
                <div>
                    <strong>重要提醒</strong>
                    <span>配置前请先完全关闭 Codex；账号密码不要复用重要账户；API Key 只粘贴到自己的配置文件中。额度包兑换码必须选择 GPT-Plus，质保补发则选择“质保补偿”。</span>
                </div>
            </div>
            <div class="warranty-static-tutorial__cta">
                <a class="btn btn-primary" href="https://api.sakms.top/register" target="_blank" rel="noopener noreferrer">
                    <i data-lucide="external-link"></i> 打开中转注册
                </a>
                <a class="btn btn-secondary" href="https://openai.com/zh-Hans-CN/codex/" target="_blank" rel="noopener noreferrer">
                    <i data-lucide="download"></i> 打开 Codex 下载页
                </a>
            </div>
        </section>
    """.strip()


def build_warranty_email_check_static_tutorial_html(matched: bool) -> str:
    return f"""
        <div class="warranty-static-tutorial warranty-static-tutorial--{'matched' if matched else 'miss'}">
            {_build_static_tutorial_hero(matched)}
            <div class="warranty-static-tutorial__grid">{''.join(_build_static_tutorial_steps())}</div>
            {_build_static_tutorial_note()}
        </div>
    """.strip()
