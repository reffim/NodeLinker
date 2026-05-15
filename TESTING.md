# Local Testing Guide for NodeLinker

이 문서는 NodeLinker 개발 환경에서 외부 서버 없이 로컬 머신만으로 프로젝트 기능과 Ansible 플레이북을 테스트하는 방법을 안내합니다.

## 1. 로컬 테스트 노드 (Local Test Nodes)
NodeLinker의 Docker Compose 개발 환경은 외부 인프라 없이도 Ansible 플레이북을 실행해 볼 수 있도록, 내장 SSH 서버가 포함된 Ubuntu 컨테이너 2대를 기본으로 제공합니다.

- **test-node-1**: 내부 DNS `test-node` (포트 `22`) / 호스트 연결 포트 `2222`
- **test-node-2**: 내부 DNS `test-node-2` (포트 `22`) / 호스트 연결 포트 `2223`

**테스트 노드 접속 정보:**
- **SSH User**: `testuser`
- **SSH Password**: `testpassword`

### UI에 테스트 노드 등록하기
1. 시스템 내 **Credentials** 메뉴(지원 예정/또는 DB 직접 입력)를 통해 비밀번호가 `testpassword`인 자격 증명을 생성합니다.
2. **Node Dashboard** 메뉴로 이동하여 **Add Node**를 클릭합니다.
3. 아래 정보를 입력하여 노드를 등록합니다:
   - **Name**: 원하시는 이름 (예: `Local Test Node 1`)
   - **Host**: `test-node` (또는 `test-node-2`)
   - **Port**: `22`
   - **SSH User**: `testuser`
   - **Credential**: 앞서 생성한 자격 증명을 선택합니다.

---

## 2. 플레이북 실행 테스트 (Playbook Testing)
노드 등록을 마치면 NodeLinker의 웹 UI를 통해 플레이북을 테스트할 수 있습니다.

1. **Playbooks** 메뉴에서 새로운 플레이북을 생성합니다.
2. 에디터에 아래와 같은 간단한 테스트 코드를 작성합니다:
```yaml
- name: Test playbook execution
  hosts: all
  tasks:
    - name: Ping the node
      ping:
    - name: Get system info
      command: uname -a
      register: sysinfo
    - debug:
        msg: "System info: {{ sysinfo.stdout }}"
```
3. 생성한 플레이북에서 **Run** 버튼을 누르고, 등록한 로컬 테스트 노드를 선택하여 실행합니다.
4. **Jobs** 메뉴로 이동하면 실시간으로 출력되는 Ansible 작업 로그를 확인할 수 있습니다.

---

## 3. 동시성 제어 테스트 (Exclusive Groups)
NodeLinker의 주요 기능 중 하나인 **Exclusive Groups(배타적 그룹)** 기능(동일 그룹 내 플레이북의 동시 실행 방지)을 테스트하는 방법입니다.

1. 두 개의 서로 다른 플레이북을 생성하되, **Exclusive Group**을 동일한 이름(예: `sys-update`)으로 지정합니다.
2. 락(Lock) 대기 상태를 확인하기 위해, 각 플레이북에 고의로 지연을 발생시키는 작업을 추가합니다:
```yaml
    - name: Simulate long running task
      command: sleep 15
```
3. 브라우저 창을 두 개 띄우거나 빠르게 두 플레이북을 동일한 테스트 노드에 연속으로 실행(Run)시킵니다.
4. **Jobs** 메뉴에서 첫 번째 작업은 `Running` 상태로 진행 중이지만, 두 번째 작업은 앞선 작업이 끝날 때까지 락을 기다리며 `Pending` 상태로 대기하는 것을 확인할 수 있습니다.

---

## 4. 백엔드 API 테스트
NodeLinker의 백엔드는 OpenAPI(Swagger) 기반의 자동화된 API 문서를 제공합니다. 프론트엔드를 거치지 않고 백엔드의 로직을 직접 테스트하고 싶을 때 활용할 수 있습니다.

- **Swagger UI**: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
- 이 화면에서 `Authorize` 버튼을 눌러 토큰을 등록한 뒤, 각종 API를 브라우저 상에서 직접 호출하고 응답을 확인할 수 있습니다.
