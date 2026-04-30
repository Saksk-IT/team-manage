# 系统更新日志

本文档遵循“按日期倒序 + 变更类型”记录方式；历史内容根据 Git 提交信息回填，具体实现以对应提交为准。

## 未发布

- 新增：后台新增独立号池，开启后前台兑换码拉人进入号池 Team，质保仍使用控制台 Team。
- 修复：控制台 Team 批量转移号池脚本输出 HTML 转义导致 JS 中断的问题，恢复多选批量操作。
- 新增：后台新增成员快照只读查询页，支持按邮箱、Team ID 与成员状态筛选。
- 新增：后台成员快照页补充统计卡片、支持 Team 账号搜索与 Team 个数范围筛选，并可直接踢出成员或撤回邀请。
- 新增：后台成员快照页支持按 Team 状态标签式多选筛选。
- 修复：Team 自动刷新遇到未捕获异常时会写入失败刷新记录并重置该 Team 计时，避免后台看不到自动刷新痕迹。
- 修复：保存 Team 自动刷新配置后立即唤醒后台自动刷新循环，确保新周期无需等待旧睡眠周期结束即可生效。
- 修复：Team 自动刷新从“全局每周期只刷 1 个”改为限流并发批量推进到期队列，避免单个 Team 长时间没有自动刷新记录。
- 修复：SQLite 部署下自动刷新批次改为串行写入，避免并发刷新时出现 `database is locked`。
- 文档：新增系统更新日志，并基于已有提交信息回填历史记录。

## 2026-04-29

### 新增

- add admin record stats and email modals（`94ab910`）
- add warranty email bulk deletion（`ebe413f`）

### 修复

- restrict warranty claims to banned latest team（`51bdc36`）
- use warranty email entries as order source（`33861e8`）
- preserve future whitelist sources after warranty sync（`1771133`）

### 其他

- 0（`b80f2b7`）

## 2026-04-28

### 新增

- paginate warranty emails and default 100 per page（`10f4bed`）
- support multiple warranty orders（`bb99d22`）
- 子管理员侧边栏展示控制台概览（`0a2d75b`）
- optimize redemption code generation modal（`ee92eef`）
- add invite queue seat reservations（`f539ee3`）
- add redemption code generation presets（`ade47a1`）
- add per-team refresh records（`3b0033e`）
- improve team filters and batch max members（`29ccb67`）
- enforce code generation seat capacity（`abe23df`）
- show seat stats on admin dashboard（`53fd098`）
- add team account multi filters（`6fccd19`）
- 支持后台侧边栏自定义排序（`b15fb1b`）
- make email whitelist global cleanup dependency（`8fdd0e5`）
- expose warranty team whitelist in sidebar（`b501c82`）

### 修复

- persist warranty order edits（`d09239e`）
- expand warranty email orders in admin（`e3b442e`）
- normalize warranty order status display（`6881db8`）
- separate concurrent warranty order teams（`4d38709`）
- 关闭前台兑换码自助撤销（`241febe`）
- preserve multi-code email invites（`b872070`）
- limit invite queue team window（`5463dc3`）
- 取消子管理员 Team 导入审核（`bf00ea9`）
- repair warranty claim before team display（`00181e2`）
- preserve warranty claim before team snapshot（`8521480`）
- prevent same email redeeming multiple codes into one team（`b913e05`）
- use usage records for code status（`8e23bb9`）
- respect warranty whitelist removals（`7ac86be`）
- unify team refresh state updates（`55eb2a0`）

### 文档

- update admin pagination default（`05973d3`）

### 重构

- unify team assignment pool（`d6e52bf`）

## 2026-04-27

### 新增

- add importer filter for pending teams（`64a2e99`）
- add import tags and review filters（`9682f4b`）
- redesign user front desk UI（`3ec96cc`）
- 优化前台服务布局（`a9d80f0`）
- add front page purchase link settings（`9830577`）

### 修复

- backfill warranty manual whitelist（`b97828f`）
- add warranty team refresh cleanup（`4fb5eae`）
- rebalance front announcement layout（`e5580fe`）
- compact front hero card（`8fbc22f`）
- separate front service cards（`d05291f`）
- 调整质保查询状态展示（`ddfd474`）

## 2026-04-26

### 新增

- combine records with email accounts（`516f898`）
- simplify email account cards（`f7a3fb8`）
- discover email accounts from entry links（`57057e4`）
- add email account workbench（`c8d6b69`）

### 修复

- normalize email link open button（`5e01488`）
- enable email fetch in combined records（`cc75241`）
- unify record copy hover style（`0095d3b`）
- expand record name copy hit area（`1edf63c`）
- expand record copy hit areas（`2495c0d`）
- require six digit email codes（`fa58d69`）
- suppress non-code email summaries（`e3ebab6`）
- extract latest email verification code（`4599e11`）
- parse email entry data-copy credentials（`90c17ba`）

## 2026-04-25

### 新增

- 精简本地记录合一展示（`0405247`）
- 增加本地记录合一导入开关（`acfab76`）
- 合并本地记录两种数据（`97e2bbf`）
- 显示 Team 质保时长快捷设置（`1c3a102`）
- support pipe sms import format（`dc9cc28`）
- batch update warranty code quotas（`0e09274`）
- add warranty email filters and bulk edits（`7b5cf0d`）
- add admin code multi filters（`8340d29`）

### 修复

- 修复本地记录导入框高度（`0b64ee7`）
- align legacy warranty status copy（`657da4c`）
- update warranty code copy（`d35f486`）
- split inline local record prefix（`be13ac5`）
- ignore local record payment prefix（`6a65ef3`）

## 2026-04-24

### 新增

- polish local records card UI（`e8dbcfd`）
- show local record card expiry（`08494e2`）
- add safe local record workbench（`2fd18ee`）
- batch classify import reviews（`dd5a7c6`）
- keep batch-only import for sub admins（`54ad8fa`）
- support sub-admin team imports（`03edac0`）
- add per-item local tool refresh（`1c2611d`）
- add system confirmation dialogs（`3519b6c`）
- refine local tool result display（`f0c87d4`）
- parse verification codes in local tools（`5118ae6`）
- enhance local tools metadata workspace（`d252e49`）
- refine local tools workbench layout（`b57b5a3`）
- add standalone local import tools page（`78f0443`）
- add admin sms helper page（`ed200f6`）
- add admin cleanup records（`0e98ca9`）

### 修复

- use warranty email limits when editing（`20678fe`）
- rename extra field label to cvv（`6f35c80`）
- remove local records format tips（`6bf2d2b`）
- show extra code in local records（`31cf742`）
- display plain text local records（`b394c91`）
- 优化本地记录字段展示复制（`f7d0fae`）
- retain sub-admin import review records（`3d0f091`）
- clarify pending team classification flow（`89f8b92`）
- keep local tool result inline（`e34c949`）
- proxy local tool code refresh（`668d2f7`）

### 文档

- mention code withdrawal in lookup description（`74bd653`）

### 样式

- align self-service withdraw title with lookup heading（`6bf9462`）

## 2026-04-23

### 新增

- allow users to withdraw bound email（`ed99851`）
- add bound email lookup on redeem page（`f3cb751`）
- auto cleanup invalid standard team emails on refresh（`505c3b7`）
- add warranty claim history records（`a5b4412`）

### 修复

- remove warranty email on warranty withdraw（`19528b6`）
- show full bound email in lookup（`d687310`）
- mark failed warranty teams unavailable（`8e3b3ef`）
- retry next warranty team on seat limit（`96a4697`）
- retry warranty invite on intercepted team（`6b9d21e`）
- limit warranty claim to one preferred team（`d5bf057`）

### 测试

- avoid warranty service mock leakage（`1ad6824`）

## 2026-04-22

### 新增

- 标注 Team 列表中的普通与质保账号（`aed96b6`）
- center customer service qr reminder modal（`1eebd9b`）
- 同步展示质保码剩余信息（`a492c4c`）
- 增强质保兑换码流程（`c7aa84c`）
- 支持质保邮箱按兑换码搜索（`6888cc8`）

### 修复

- 将 Team 账号类型改为独立列展示（`c50609f`）
- 修正质保状态查询对封禁 team 的处理（`953cc67`）
- 将 deactivated workspace 视为封禁（`546df66`）
- 强制质保状态查询实时刷新（`9546444`）
- persist customer service qr uploads（`2436656`）
- 更新前台兑换服务文案（`29dea40`）
- 恢复质保邮箱列表兑换码查询（`59a40c9`）
- refresh codes page after team import（`2440027`）
- 修正质保码自动入列判断（`66f6624`）
- 统一质保邮箱编辑默认值（`e4dd75e`）
- default warranty email form to 30 days 10 claims（`b75eb3e`）

## 2026-04-21

### 修复

- 调整质保邮箱默认值（`aa429b1`）
- 优先使用质保邮箱列表中的最新 Team（`28902a5`）

## 2026-04-20

### 新增

- add transition preview entry for user page（`9a29488`）

### 修复

- remove transition preview entry（`aaf28d7`）

## 2026-04-19

### 新增

- add calming transition overlay for user waits（`b011601`）

### 修复

- refresh bound team before redeem（`e1e3e73`）

## 2026-04-18

### 其他

- 0（`ed9d0cd`）
- fix team import validation and admin auto refresh（`c33178d`）

## 2026-04-15

### 新增

- move front notice and support beside card（`8df0f3b`）
- add customizable front notice and support（`e3a2090`）
- add docker compose dev hot reload（`0d919ab`）
- refresh warranty status before returning（`fd75432`）
- sync team member snapshots for warranty（`081cbac`）
- update warranty email status flow（`afa88e7`）

## 2026-04-14

### 修复

- improve warranty email edit feedback（`5df2643`）

## 2026-04-01

### 新增

- add code cleanup and bulk delete support（`2771410`）
- add configurable default team max members（`352109d`）

## 2026-03-31

### 新增

- add admin warranty service toggle（`0812a8a`）

### 修复

- align template response calls with current starlette（`1b82bea`）

## 2026-03-27

### 新增

- validate fake warranty claims before success（`8de54fc`）
- persist fake warranty seat display（`c65a388`）
- add warranty fake success toggle（`53e58f9`）

### 修复

- use outlook suffix for fake warranty team email（`cd32c2c`）

## 2026-03-25

### 新增

- add automatic team refresh and status sync（`5d2573a`）
- support team transfer and batch code export（`2898e3c`）

### 修复

- 质保申请仅检查可用team（`cf813e9`）

### 合并

- Merge branch 'codex/batch-action-progress-modal'（`d20a249`）

## 2026-03-24

### 新增

- add blocking batch action progress modal（`0b98be2`）
- show warranty remaining status and errors（`f73d4a5`）
- support dual warranty super codes（`05e4c06`）
- add warranty teams and super code flow（`0f71f74`）

### 修复

- persist team status after refresh（`bafe066`）
- avoid false token expiry during team refresh（`a30c42e`）

## 2026-03-23

### 新增

- support full team json import（`a4de11f`）
- 补充邮箱确认弹窗提示（`c2c55c9`）
- 增加邮箱确认兑换弹窗（`492b89d`）

## 2026-03-22

### 新增

- add copy action for batch imported codes（`89221fb`）
- show redemption usage in bound code modal（`16bbcc8`）
- export codes by team（`ebce5b3`）
- improve redemption code export（`1317844`）

### 修复

- keep admin sidebar fixed and hide footer（`834f285`）
- show batch device auth failure details（`c63aa45`）

## 2026-03-21

### 修复

- verify code before redeem on frontend（`8c45a5e`）
- block used warranty codes in redeem flow（`ce9e356`）
- stabilize https static assets and deploy config（`621d3b1`）

### 文档

- add deployment and server command handbook（`f744947`）

### 其他

- init my deploy repo（`9e14cd7`）

## 2026-03-15

### 新增

- Implement the complete redeem flow service for redemption code verification, team selection, and user joining.（`05f83de`）

## 2026-03-10

### 新增

- implement user redemption page with associated frontend logic and backend warranty service.（`951314d`）
- implement redemption flow service including code validation, automatic team selection, and team joining functionality.（`12bc66c`）
- add redeem flow service（`2d98c58`）
- introduce database module（`69a8928`）
- Add warranty and redeem flow service modules.（`993674b`）
- Add redeem flow service.（`a6c2c93`）
- Add TeamService for managing team account status and access token lifecycle.（`a7cc9ae`）
- Implement TeamService for managing Team account lifecycle and introduce a redeem flow service.（`25ebf23`）
- add redeem flow service to coordinate redemption code verification, team selection, and joining a team.（`e3a655a`）
- Add redeem flow service to coordinate redemption code verification, team selection, and team joining.（`994c25d`）
- introduce admin dashboard with team management interface and backend service.（`8198bd5`）
- add admin dashboard with team management, statistics, filtering, and batch operations.（`e25212a`）
- Implement user redemption functionality for codes to join teams.（`e1c0c8f`）
- Add database models for team and redemption management, and implement ChatGPT API service with session and proxy handling.（`a848544`）
- Add admin panel with comprehensive team and redemption code management functionalities.（`be40f73`）
- Introduce Team and RedeemFlow services for comprehensive team account management and redemption code handling.（`b139835`）

## 2026-03-08

### 新增

- add TeamService for managing Team accounts, including token refresh and status updates based on API responses.（`97dca06`）
- introduce team management service with automated token refresh and admin routes for account management（`a3d8cbd`）

## 2026-03-07

### 新增

- add admin panel with routes and services for team and redemption code management.（`93aea43`）

## 2026-03-05

### 新增

- implement redeem flow service（`fdba828`）
- 添加兑换流程服务（`b56f56d`）

## 2026-03-04

### 新增

- implement redeem flow service（`e6b22b7`）
- Implement Team management service with token refresh, error handling, redemption flow, and warranty features.（`1b9dd56`）
- Add new services for redeem flow and warranty management.（`8d376be`）
- add redeem flow service（`79bb4b6`）
- Add redemption code verification and team joining functionality with corresponding team management services.（`5dbec27`）
- implement TeamService for managing team accounts, including token refresh and API error handling.（`8a8dc49`）
- add new services for team management, warranty, and redeem flow.（`b49c6cd`）
- add Team management service with token refresh, session token handling, and API error management.（`40742d4`）
- Add team management and redeem flow services.（`2550545`）
- introduce ChatGPT API service for managing team members and invites, featuring session isolation and retry mechanisms.（`ae48d7d`）
- Implement ChatGPT API service for team member management, including proxy configuration.（`4c9299a`）
- implement ChatGPT API service for team member management, including invite, list, and delete functionalities with robust request handling.（`6fe7de5`）

## 2026-03-03

### 新增

- add Team management and redeem flow services.（`81c89df`）

## 2026-03-02

### 新增

- implement core team management models and service logic, including API error handling for team status.（`f5edfbf`）
- add admin panel with routes for team and redemption code management.（`f9a0b56`）
- Add ChatGPT API service for team member and invite management.（`571cd34`）

## 2026-02-26

### 新增

- add notification service（`b6b54a2`）
- Add team management, redeem flow, and notification services, along with an admin settings template.（`e9d6636`）
- Implement initial application structure, base HTML template, and team import modals.（`2d3f76e`）
- Initialize core application structure with configuration and database setup.（`cec66d1`）
- Introduce a comprehensive admin settings page for managing proxy, password, logging, and webhook configurations, alongside new redemption flow services and authentication dependencies.（`c1c0497`）
- Add redeem page for GPT Team codes, including email and code input, and a warranty inquiry section.（`fa23367`）
- Add ChatGPT API service for Team management and introduce redeem flow service.（`82c0561`）

### 维护

- update project dependencies（`a6bace8`）

## 2026-02-25

### 新增

- implement TeamService for managing team accounts, including token refresh, error handling, and import functionalities.（`fd8cf71`）

## 2026-02-24

### 新增

- add ChatGPT backend API service for team management functionalities.（`5791dc0`）
- add Team management service with ChatGPT integration for account and token handling.（`130559c`）
- Add admin dashboard for team management with statistics, team listing, search, pagination, and action buttons.（`92a650b`）
- Implement team management service with token refresh, API error handling, and initial admin UI components.（`c4277b5`）

## 2026-02-12

### 新增

- Add a new comprehensive CSS design system including variables, base styles, layout, and UI components.（`cae146d`）
- Implement a minimalist and dynamic CSS design system with global variables, base styles, and core UI components.（`23f603d`）
- add global stylesheet with base styles and common UI components.（`f322e7b`）
- Add admin redemption code management page with statistics, filtering, and bulk actions.（`9fa4570`）
- Add a comprehensive minimalist design system including base styles, layout, and UI components.（`64ea086`）
- Add initial CSS design system and core styling with variables, layout, and UI components.（`f37bad2`）
- add a new minimalist and dynamic CSS design system and base HTML template.（`75fad41`）
- add admin page for redemption code management with statistics, filtering, search, and bulk actions（`96d1e06`）
- introduce a new minimalist design system and add the admin codes index page.（`c6abe5d`）
- Add initial CSS design system and core styling for the application.（`98c77a3`）
- Implement initial admin module with dedicated routes, templates, and a comprehensive minimalist design system.（`bf3965b`）
- add core CSS design system including variables, base styles, layout, and UI components（`a9908ae`）
- Implement a comprehensive CSS design system with base styles, layout, and UI components.（`d50242c`）
- add warranty service module（`25088ba`）
- implement Team management service for account import, token refresh, and status handling.（`92cc1a9`）
- add TeamService to manage team account import, synchronization, and member management.（`16cdd60`）
- Add TeamService for managing team accounts and introduce redeem flow service.（`3713cae`）

## 2026-02-07

### 新增

- Add automatic database migration utility to introduce new warranty and team token/role related columns.（`1456bae`）
- implement redemption code verification and team joining functionality（`53c1ace`）

## 2026-02-06

### 新增

- Implement core database models, ChatGPT API service, and initial admin UI components.（`46058f3`）

## 2026-02-03

### 新增

- Introduce `RedeemFlowService` to manage redemption codes, team selection, and user joining, add `TeamService`, and delete `migrate_add_warranty.py`.（`69f3256`）
- Implement admin panel for managing usage records, including statistics, search, pagination, and a record withdrawal feature.（`8569303`）
- implement new services for ChatGPT API interaction, team management, and warranty handling.（`e00893d`）
- implement warranty service for checking user warranty status and redemption records with rate limiting and team synchronization.（`29b0adb`）
- add TeamService for managing Team accounts, including import, synchronization, and token refresh.（`d2a98d8`）

## 2026-02-02

### 新增

- introduce TeamService for managing team accounts, including token refresh and import.（`a3dd950`）
- add TeamService for managing team accounts, including token refresh and import functionality.（`a022ece`）
- implement admin dashboard for managing teams and redemption codes.（`5aac5ad`）
- introduce `TeamService` for managing Team accounts, including access token refresh and import functionality.（`b46a08d`）

## 2026-02-01

### 新增

- add TeamService for managing team accounts, including import, synchronization, and token refreshing.（`6bb10ad`）
- Implement redemption code system with API routes for code verification and team joining.（`5e9c579`）

## 2026-01-31

### 新增

- add warranty service for checking user warranty status and redemption UI.（`2974654`）
- Add API and service for checking product warranty status by email or redemption code.（`50e6bf7`）
- add automatic database migration module to support new warranty and token refresh fields（`432d2b0`）
- 新增 Team 管理服务及 Team 和 TeamAccount 数据模型。（`e59ce1e`）
- implement frontend JavaScript logic for the user redemption page, including code validation, team selection, and redemption confirmation.（`1e00686`）
- Implement warranty service to check user warranty status by email or redemption code, including rate limiting and banned team detection.（`f43c86f`）
- add client-side JavaScript for the user redemption page, including code verification, team selection, and result display.（`2a642a8`）
- Introduce warranty service for checking redemption status by email or code.（`798054b`）
- introduce redeem.js to manage user redemption flow, verifying codes, allowing team selection, and showing redemption status.（`adde4aa`）
- implement redemption flow service and core redemption logic.（`9649ead`）
- implement user redemption flow with new CSS, JavaScript, and Python service.（`09044c5`）
- introduce RedeemFlowService for coordinating redemption code validation and team joining.（`4e63e6f`）
- Introduce team management service for account import and token handling, along with new admin UI template and styling.（`56e7a6c`）
- Implement ChatGPTService for managing team members and invitations through the backend API.（`f5394c1`）
- implement redemption flow service and API routes for code redemption and team joining.（`f359347`）
- introduce new minimalist design system and initial redeem flow and team service modules.（`39b9fde`）
- implement redemption code management service for generating and validating redemption codes.（`b4eb0d8`）
- Implement base HTML template and core CSS for the GPT Team Management System, including navigation, content blocks, and interactive modals.（`b1513a1`）
- add admin panel with functionalities for managing teams and redemption codes.（`03bcf59`）
- implement new `RedeemFlowService` to manage redemption code validation, team selection, and user joining with transactional integrity.（`efafebc`）
- add RedeemFlowService to coordinate user redemption, team selection, and transaction processing with concurrency control.（`fe6bb08`）
- add API and service for checking product warranty status by email or redemption code, including rate limiting.（`4daa894`）
- implement RedeemFlowService to manage the user redemption process, including code verification, team selection, and joining with concurrency control.（`c6b9566`）
- Implement redemption flow service for code validation, team selection, and user joining.（`c93c62d`）
- add ChatGPT API service for team management, including member invitation and listing, with robust request handling.（`a780452`）
- Add admin dashboard page with team management features and a base template.（`b89997e`）
- add TeamService for managing Team accounts, including import and token refresh.（`e354921`）
- add base HTML template with navigation, sidebar, and modals for team import and code generation（`bb403cc`）
- implement a redemption system for users to redeem codes and join teams, including new services, models, routes, and UI.（`252b431`）
- Introduce initial GPT team management system including admin routes, database models, services, and frontend utilities for authentication and team management.（`340d358`）
- implement initial team management system with admin dashboard and user redemption flow.（`b007df5`）

## 2026-01-30

### 新增

- Implement GPT Team redemption and warranty query system with new database models and frontend logic.（`83cde5e`）
- introduce database models for team management and implement ChatGPT API service.（`36dd30c`）

## 2026-01-29

### 新增

- Add initial comprehensive CSS stylesheet with a minimalist and dynamic design system.（`c5b1667`）
- refactor admin dashboard UI and fix pagination/modal display issues（`2af7d1c`）
- refactor admin dashboard to white minimalist design and fix pagination error（`d11871c`）
- add search functionality to team list by email, account id, name, and team id（`bb75585`）

### 修复

- fix batch import 'invalid import type' error（`bf8f7b4`）

### 文档

- update README.md（`61e1147`）

## 2026-01-28

### 新增

- 实现批量导入进度显示功能 (支持 StreamingResponse 和实时 UI 更新)（`13f82ce`）
- redemption code page support search by code or email（`2fb629a`）
- add pagination for team and redemption code lists（`810df9a`）
- 优化 Team 导入逻辑，支持手动指定 Account ID 及自动导入所有活跃 Team（`52f74cb`）
- update proxy settings and redeem flow（`35e273a`）

### 修复

- import func in redemption service（`2c4aa3f`）
- correct member field mapping for ChatGPT API response（`c2de500`）
- resolve sqlite3 database is locked by optimizing transaction flow and enabling WAL mode（`866ca7b`）

## 2026-01-25

### 新增

- switch system timezone to Asia/Shanghai (CST)（`61e7343`）
- customize redemption error message for used codes and fix frontend display（`1c6325c`）

### 修复

- add pytz to requirements and TIMEZONE to .env.example（`4b9d532`）

## 2026-01-24

### 新增

- 使用记录支持用户邮箱模糊搜索，重构搜索过滤逻辑（`96fe10e`）
- add account id column to team list in admin dashboard（`232c043`）
- optimize team import regex and support multiple formats (email----jwt----uuid, uuid----jwt)（`69ded6c`）
- Team 列表显示 ID 并在使用记录搜索中安全解析 team_id 修复报错（`dc4bb50`）
- simplify member management into modals and add pending invitation support（`15c393b`）

### 修复

- 修复 .env 中端口配置不生效的问题，移除硬编码端口（`da28d78`）

## 2026-01-23

### 新增

- 简化兑换流程自动分配Team，显示剩余车位（`8b29fba`）
- add global exception handler to redirect unauthorized HTML requests to login page（`edaac33`）
- 配置 Docker 部署方案并更新文档（`3164405`）
- refactor team member management to modal and beautify UI tables（`6cb0ccd`）
- complete core features and basic UI implementation, include security fixes（`f19c5f0`）

### 修复

- 强制兑换码生成结果显示样式，确保不出现白色背景（`c4d3c04`）
- 修复兑换码显示白框问题及复制按钮逻辑报错（`88325d5`）
- 实现自动初始化数据库逻辑并优化 Docker 挂载方式（`99d1303`）
- dependency issues and sync application port to 8008（`99b8395`）

### 样式

- 完善全局 CSS 变量定义及 code 标签样式（`8ed1ee5`）
- overhaul UI with premium dark mode and glassmorphism（`d9a7c90`）

### 合并

- Merge remote main branch（`4931d6f`）

### 其他

- 更改端口号（`b49dedb`）
- Initial commit（`f32b5af`）
- 初始提交：GPT Team管理系统基础功能（`63d65e1`）
