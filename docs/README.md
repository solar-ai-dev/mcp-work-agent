# Product Canonical

이 디렉터리는 현재 제품 계약과 실행에 필요한 기술 계약을 관리한다. 작업 이력, 완료 증명, 코드 inventory는 Git history와 GitHub Issue/PR가 소유하며 Canonical에 복제하지 않는다.

## 읽는 순서

1. [Project Source Guide](canonical/00-project-source-guide.md)에서 concern owner를 찾는다.
2. 제품 범위는 [Requirements PRD](canonical/01-requirements-prd.md), 사용자 동작은 [Functional Definition](canonical/01-a-functional-definition.md), 정책은 [Policy Definition](canonical/01-b-policy-definition.md)을 읽는다.
3. UI·Domain·Retrieval·Workflow·Interface 등 변경 대상의 owning Canonical을 읽는다.
4. repository placement, naming, dependency, single authority는 [Repository Architecture](canonical/16-repository-architecture/16-repository-architecture-source.md)를 따른다.

`canonical/`의 각 문서는 자기 concern만 소유한다. 다른 문서의 전체 상태표, API field, 알고리즘, 코드 경로를 복제하지 않고 필요한 local consequence와 개념 참조만 둔다. 문서 버전은 해당 문서에만 적용하며 API/wire schema, typed contract, checkpoint compatibility, migration, manifest/hash 버전과 구분한다.

`database/migrations/`는 적용 순서와 checksum을 보존하는 실행 migration의 문서 미러다. 적용된 migration은 수정·재번호·이동·squash하지 않는다.

제품 코드·테스트의 존재는 그 동작이 제품 계약이라는 뜻이 아니며, Canonical의 요구사항은 구현·테스트·Live 검증 완료를 뜻하지 않는다. 구현 상태는 현재 production caller와 검증 근거로 판단한다.
