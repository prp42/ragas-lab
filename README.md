# RAGAS 실험실

내 컴퓨터에서 돌아가는 **Dify RAG 챗봇**을 [RAGAS](https://docs.ragas.io) 4대 지표로 측정하는 웹앱입니다.
Dify 공유 링크와 질문 몇 개만 있으면 됩니다. API 키를 Dify에서 따로 만들 필요가 없습니다.

- **4대 지표**: Faithfulness(충실성) · Answer Relevancy(답변 관련성) · Context Precision(맥락 정밀도) · Context Recall(맥락 재현율)
- **진단**: 낮은 지표가 검색 문제인지 생성 문제인지, 무엇을 고치면 되는지 알려 줍니다.
- **질문별 결과**: 답변, 검색된 근거 문서, 지표를 Faithfulness가 낮은 순서로 보여 줍니다.
- **전후 비교**: 앱을 하나 고친 뒤 다시 재고 이전 실행과 나란히 비교합니다.
- **가드레일 점검**: 공격 프롬프트 5개(범위 밖 질문, 프롬프트 인젝션 등)를 보내고 막았는지 직접 판정합니다.
- **CSV 내려받기**: 평가 리포트에 바로 쓸 수 있습니다.

```
브라우저 ──▶ RAGAS 실험실 (http://localhost:8030)
              ├─ 내 Dify 앱 (http://localhost/chat/...)  ← 질문을 보내 답변 + 검색 근거 수집
              ├─ 판사 LLM (OpenRouter API)                ← 지표 채점
              └─ 임베딩 (내 컴퓨터의 Ollama)               ← Answer Relevancy 계산
```

## 준비물

- **Linux** + **Docker Engine**(Docker Compose 포함). Docker 없이 Python만으로도 실행할 수 있습니다(아래 참고).
- 내 컴퓨터에서 실행 중인 **Dify**(`http://localhost`)와, 그 안의 **채팅형 RAG 앱**(Chatbot 또는 Chatflow).
- 내 컴퓨터의 **[Ollama](https://ollama.com)**: Dify 앱에 쓰고 있는 그 Ollama로 임베딩을 계산합니다.
- **OpenRouter API 키**: 판사 LLM(채점) 호출에 씁니다. https://openrouter.ai/keys 에서 만들거나 수업에서 받은 키를 쓰세요.

## 1. Dify 앱 준비

1. Dify에서 앱을 열고 **Features**(기능)에서 **Citations and Attributions**(인용 및 출처)를 켭니다.
   꺼져 있으면 검색 근거를 받을 수 없어 Context 지표를 잴 수 없습니다.
2. **Publish**(게시)한 뒤 **Run App**(웹앱 열기)을 눌러 나오는 주소를 복사합니다.
   예: `http://localhost/chat/AbCdEfGh12345678`
3. 앱에 **필수 입력 변수**가 있으면 선택 사항으로 바꾸세요. 실험실은 질문만 보냅니다.

## 2. 설치와 실행 (Docker)

```bash
git clone https://github.com/prp42/ragas-lab.git
cd ragas-lab
cp .env.example .env
nano .env                  # JUDGE_API_KEY 에 OpenRouter 키 입력 (아래 표 참고)
docker compose up -d --build
```

브라우저에서 **http://localhost:8030** 을 엽니다.

- 로그 보기: `docker compose logs -f`
- 끄기: `docker compose down`
- 코드 업데이트 후 다시 시작: `git pull && docker compose up -d --build`

`docker-compose.yml`은 Linux의 **host 네트워크**를 씁니다. 그래서 컨테이너 안의 `localhost`가 내 컴퓨터를 가리켜
`http://localhost`의 Dify와 `localhost:11434`의 Ollama에 그대로 연결됩니다.
Docker Desktop은 host 네트워크가 다르게 동작하므로 아래 "Docker 없이 실행"을 쓰세요.

### Docker 없이 실행

Python 3.10 이상이 있으면 됩니다.

```bash
cp .env.example .env && nano .env
./scripts/run-local.sh      # 처음 한 번은 가상환경을 만들고 패키지를 설치합니다
```

## 3. `.env` 설정

| 항목 | 설명 | 예 |
|---|---|---|
| `DIFY_BASE_URL` | 공유 링크의 앞부분. 이 주소의 링크만 받습니다. | `http://localhost` (포트가 있으면 `http://localhost:8088`) |
| `JUDGE_API_KEY` | **OpenRouter 키 (필수)** | `sk-or-v1-...` |
| `JUDGE_MODEL` | 판사 모델. 수업 측정과 같게 두세요. | `anthropic/claude-sonnet-5` |
| `EMBED_BASE_URL` / `EMBED_MODEL` | Answer Relevancy용 임베딩 (Ollama) | `http://localhost:11434/v1`, `bge-m3` |
| `PORT` | 실험실 주소의 포트 | `8030` |
| `MAX_QUESTIONS` | 한 번에 평가할 질문 수 상한 | `10` |
| `CLASS_CODE` | **비워 두세요.** 비우면 로그인 화면과 하루 횟수 제한이 없습니다. | |

임베딩 모델을 먼저 받아 두세요. Dify에서 이미 쓰는 임베딩 모델(예: `nomic-embed-text`)이 있으면 `EMBED_MODEL`에 그 이름을 적어도 됩니다.

```bash
ollama pull bge-m3
```

> 판사 LLM은 질문 1개당 여러 번 호출되므로 질문 10개 실행에 OpenRouter 크레딧이 조금 듭니다.
> 판사 모델을 바꾸면 점수 기준이 달라지니 전후 비교 중에는 같은 모델을 쓰세요.
> 판사(OpenRouter)와 내 앱의 생성 모델(Ollama)이 서로 다르므로, 판사가 자기 답을 후하게 주는 편향은 생기지 않습니다.

## 4. 사용 순서 (측정 → 진단 → 하나만 고치기 → 재측정)

1. **평가 실행** 탭에서 공유 링크를 붙여넣고 **연결 확인**을 누릅니다. 앱 이름과 "근거 인용 켜짐"이 보이면 준비 완료입니다.
2. 질문을 최대 10개 씁니다. **정답**을 적으면 검색 지표(Context Precision, Recall)까지 잽니다.
   문서에 답이 없는 질문도 1~2개 넣고, 그 질문의 정답은 비워 두세요.
3. **평가 시작**. 질문당 몇 초~수십 초, 채점에 1~3분이 걸립니다. 페이지를 닫아도 계속 진행되고 **실행 기록**에서 결과를 다시 볼 수 있습니다.
4. 결과의 **진단**을 보고 한 가지만 고칩니다. 예: 지식베이스 Top K, 청크 크기, 시스템 프롬프트.
   Dify에서 다시 Publish한 뒤 **같은 질문으로** 다시 재고 **이전 실행과 비교**합니다.
5. **가드레일 점검** 탭에서 공격 프롬프트 결과를 확인하고, 레일을 추가한 뒤 다시 점검합니다.

### 결과를 읽을 때 주의할 점

- 판사도 LLM이라 같은 입력이어도 점수가 실행마다 흔들립니다. **±0.05보다 작은 변화는 개선이라고 보기 어렵습니다.**
- 평균만 보지 말고 **점수가 낮은 질문을 열어** 답변과 근거를 직접 읽으세요.
- "문서에서 찾을 수 없습니다" 같은 정직한 거절은 Answer Relevancy가 0점이 됩니다. 지표의 한계이지 나쁜 답이 아닐 수 있습니다.
- Faithfulness는 **근거와의 일치**를 잴 뿐 사실 여부는 재지 않습니다. 근거 자체가 틀리거나 잘렸으면 높은 점수의 틀린 답이 나옵니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| "…형식의 공유 링크만 사용할 수 있습니다" | `.env`의 `DIFY_BASE_URL`이 공유 링크 앞부분(포트 포함)과 같은지 확인 |
| "앱을 찾을 수 없습니다" | Dify에서 앱을 Publish했는지, 웹앱 공개가 켜져 있는지 확인 |
| 근거 인용 꺼짐 경고 | Dify 앱 Features → Citations and Attributions 켜고 다시 Publish |
| 채점 중 오류 | `docker compose logs` 확인. OpenRouter 키·크레딧·모델명, Ollama 임베딩(`curl http://localhost:11434/v1/models`, `ollama list`) 점검 |
| 점수가 `–` | 판사 응답 형식 오류. 다시 실행하거나 `docker compose logs`로 원인 확인 |
| `http://localhost:8030`이 안 열림 | 다른 프로그램이 8030을 쓰는지 확인하고 `.env`의 `PORT` 변경 |

## 수업 서버로 운영하기 (교사용)

여러 학생이 한 서버를 함께 쓰게 하려면 `.env`에 `CLASS_CODE`(학생용 수업 코드)와 `TEACHER_CODE`를 넣습니다.
그러면 수업 코드와 학번으로 로그인하고, 학생마다 하루 `RUNS_PER_DAY`회로 제한되며, 교사 코드로는 전체 학생의 실행 기록을 볼 수 있습니다.
`DIFY_BASE_URL`을 수업용 Dify 주소(예: `https://dify.example.com`)로 바꾸고, 외부 공개는 리버스 프록시나 터널로 `localhost:PORT`를 연결하세요.

## 개발

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q tests
```

RAGAS는 0.2.15로 고정되어 있습니다. 최신 버전은 지표 클래스 위치가 바뀌었습니다.
