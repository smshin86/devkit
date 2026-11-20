# CREDITS — devkit이 가져온 곳

devkit의 스킬 글은 다른 사람들이 만든 도구를 옆에 놓고 읽으며 썼다. 문장을 우리말로 옮겨 쓴 곳은 출처를 적고,
허락 글(라이선스)을 확인한 만큼 아래에 붙인다. 생각만 가져온 곳도 고마운 마음으로 적는다.
저장소 주소는 `https://github.com/<소유자>/<저장소>` 꼴이다.

## 가져온 곳 — 문장을 우리말로 옮겨 쓴 곳

"한 줄 번역"은 원문의 한두 줄을 우리말로 옮긴 것이다. "요약해 다시 씀"은 원문의 틀(칸·차례·목록)을 따라 우리말로
줄여 다시 쓴 것으로, 만든 쪽 보고에는 없고 구현 계획표에만 "문장"으로 적혀 있어 넉넉하게 적었다.

| 저장소 | 파일 | 가져온 것 | 옮긴 정도 | 쓰인 스킬 |
|---|---|---|---|---|
| obra/superpowers | `skills/brainstorming/SKILL.md` | "A default they never heard is one they couldn't reject" — 처음 듣는 기본값은 사용자가 거절할 수 없으니 소리 내어 말한다 | 한 줄 번역 | `intake` |
| DietrichGebert/ponytail | `.agents/rules/ponytail.md` | `shortcut:` 줄의 꼴 — "지름길: 한계, 언제 올릴지" | 한 줄 번역 | `find`, `build` |
| DietrichGebert/ponytail | `.agents/rules/ponytail.md` | 끝에 건너뛴 것·안 본 것을 말하기, 줄이지 않는 것 목록, 고치기 전에 닿아야 하는 곳 | 요약해 다시 씀 | `start`, `find`, `build` |
| addyosmani/agent-skills | `skills/frontend-ui-engineering/SKILL.md` | "Avoid the AI Aesthetic" 표 | 표를 우리말로 옮김 | `find`(`look.md`) |
| addyosmani/agent-skills | `skills/doubt-driven-development/SKILL.md` | 적대적 검토를 부탁하는 문구 | 한 줄 번역 | `review`(`fresh-eye.md`) |
| addyosmani/agent-skills | `skills/using-agent-skills/SKILL.md` | 가정을 먼저 말하고 "틀리면 지금 말해 달라"고 하는 블록 | 요약해 다시 씀 | `start` |
| cloudflare/security-audit-skill | `skills/security-audit/SKILL.md` | "이 후보를 만든 것은 당신이 아니다. 문제가 아님을 보여 보라" | 한 줄 번역 | `review`(`security-sweep.md`, `SKILL.md`) |
| cloudflare/security-audit-skill | `skills/security-audit/WEB-PROTOCOL-AND-AUTH.md` | "가장 약한 옆길이 잠금을 정한다" | 한 줄 번역 | `review`(`security-sweep.md`, `SKILL.md`) |
| EveryInc/compound-engineering-plugin | `skills/ce-compound/SKILL.md` | "이 줄이 없으면 … 한참 찾겠는가" | 한 줄 번역 | `wrap-up`(`SKILL.md`, `write-back.md`) |
| obra/superpowers | `skills/subagent-driven-development/implementer-prompt.md`, `references/handling-reports.md`, `skills/test-driven-development/SKILL.md` | 맡길 글의 칸, 보고 상태 넷과 받는 법, 실패를 먼저 본다 | 요약해 다시 씀 | `build` |
| mattpocock/skills | `skills/engineering/tdd/SKILL.md` | 나쁜 시험 셋, 시험 하나 → 구현 하나 | 요약해 다시 씀 | `build`(`tests.md`) |
| gsd-build/get-shit-done | `agents/gsd-verifier.md` | 확인의 네 겹, 이음매 꼴, 속 빈 꼴 | 요약해 다시 씀 | `verify` |

옛 devkit 0.1.0의 스킬 셋(만들 것 목록, 동시에 만들기, 화면 지도)에서 옮긴 문장은 우리 것이라 출처 표기 대상이 아니다.

## 생각만 가져온 것 — 문장은 옮기지 않았다

- **mattpocock/skills** (`https://github.com/mattpocock/skills`): grilling, to-spec, domain-modeling, research, to-tickets, implement, implement-spec, tdd(생각 부분), code-review, retro, handoff, wait-what, wizard, writing-for-agents, codebase-design(같이 바뀌는 것을 한 곳에)
- **addyosmani/agent-skills** (`https://github.com/addyosmani/agent-skills`): interview-me, spec-driven-development, source-driven-development, context-engineering, planning-and-task-breakdown, incremental-implementation, test-driven-development, browser-testing-with-devtools, code-review-and-quality, security-and-hardening, documentation-and-adrs
- **obra/superpowers** (`https://github.com/obra/superpowers`): subagent-driven-development, dispatching-parallel-agents, systematic-debugging, verification-before-completion, test-driven-development, receiving-code-review, code-reviewer, finishing-a-development-branch, using-superpowers, writing-skills, writing-plans(계획의 "File Structure")
- **gsd-build/get-shit-done** (`https://github.com/gsd-build/get-shit-done`): pattern-mapper, codebase-mapper, gsd-verifier, verify-work, map-codebase(넷으로 나눠 살피기, 손이 글을 직접 쓰고 자리·줄 수만 돌려주기, 길 안내의 바깥과 닿는 곳·조심할 곳 칸, 읽지 않는 파일 꼴)
- **garrytan/gstack** (`https://github.com/garrytan/gstack`): ETHOS, review, cso, learn, qa, verify
- **EveryInc/compound-engineering-plugin** (`https://github.com/EveryInc/compound-engineering-plugin`): ce-work
- **Fission-AI/OpenSpec** (`https://github.com/Fission-AI/OpenSpec`): 바뀌는 것만 적는 제안 꼴, 요구마다 장면
- **buildermethods/agent-os** (`https://github.com/buildermethods/agent-os`): discover-standards, inject-standards (프로젝트 방식을 영역별로 뽑아 두고 닿는 것만 꺼내기)
- **forrestchang/andrej-karpathy-skills** (`https://github.com/forrestchang/andrej-karpathy-skills`): 네 원칙의 생각만. 이 저장소는 허락 파일이 없어 **문장을 옮기지 않았다.**
- **agentsmd/agents.md** (`https://github.com/agentsmd/agents.md`): 프로젝트 맨 위 `AGENTS.md` 한 장에 여러 AI 도구가 읽을 안내를 두는 방식
- **google-labs-code/design.md** (`https://github.com/google-labs-code/design.md`): 화면 모양(색·글꼴·간격)을 값으로 적는 방식
- **humanlayer/humanlayer** (`https://github.com/humanlayer/humanlayer`): codebase-analyzer, codebase-pattern-finder (있는 것을 평하지 않고 그대로 적기)
- **affaan-m/ECC** (`https://github.com/affaan-m/ECC`): update-codemaps (일 종류마다 한 줄 길), codebase-onboarding (짐작하지 않고 코드를 믿기)
- **tobihagemann/turbo** (`https://github.com/tobihagemann/turbo`): survey-patterns (코드에 적힌 임시 표시를 세기)

## 허락 글(라이선스)

2026-11-18에 각 저장소의 `LICENSE` 파일에서 확인한 것이다. 아래 아홉 곳과 obra/superpowers는 모두 MIT이고, MIT 글은 저작권 줄만 다르고 본문이 같다. 본문은 맨 아래에 한 번 붙인다.

| 저장소 | 허락 | 저작권 줄 |
|---|---|---|
| obra/superpowers | MIT | `Copyright (c) 2025 Jesse Vincent` |
| mattpocock/skills | MIT | `Copyright (c) 2026 Matt Pocock` |
| addyosmani/agent-skills | MIT | `Copyright (c) 2025 Addy Osmani` |
| DietrichGebert/ponytail | MIT | `Copyright (c) 2026 DietrichGebert` |
| cloudflare/security-audit-skill | MIT | `Copyright (c) 2025-2026 Cloudflare, Inc.` |
| EveryInc/compound-engineering-plugin | MIT | `Copyright (c) 2025 Every` |
| gsd-build/get-shit-done | MIT | `Copyright (c) 2025 Lex Christopherson` |
| garrytan/gstack | MIT | `Copyright (c) 2026 Garry Tan` |
| Fission-AI/OpenSpec | MIT | `Copyright (c) 2025 FISSION AI INC` |
| buildermethods/agent-os | MIT | `Copyright (c) 2025 CasJam Media LLC (Builder Methods)` |
| forrestchang/andrej-karpathy-skills | 허락 파일 없음 | 그래서 문장을 옮기지 않았다 |

### MIT License 본문 (저작권 줄은 위 표의 것으로 저장소마다 바뀐다 — 아래는 obra/superpowers의 것)

```
MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
