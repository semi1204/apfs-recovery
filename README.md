# apfs-recovery

폰에서 빠른 포맷(exFAT)된 외장 SSD의 옛 APFS 볼륨을, 남아 있는 FS-tree 노드만으로 복구한 스크립트.
2026-10-09, Corsair EX400U 1TB. 원본 디스크에는 읽기만 한다.

## 순서

```sh
python3 scan.py /dev/rdiskN apfs.db 0 165        # 컨테이너를 훑어 FS-tree 리프 레코드를 SQLite로 (START_LBA 환경변수로 기준점 변경)
python3 build.py apfs.db out                     # xid 최신 레코드로 트리 재구성 -> out/tree.json, listing.tsv
python3 extract.py out/tree.json DEST [prefix …] # 익스텐트를 그대로 읽어 파일로 복사 (이어하기 가능)
```

Windows에서 같은 추출 + SHA-256 기록, Mac 복구본과 표본 대조:

```sh
python3 sample_hash.py                                               # Mac: 표본 해시 -> sample_hashes.json
python extract_win.py tree.json \\.\PhysicalDriveN C:\dest [prefix …] # Windows(관리자)
python compare_win.py tree.json sample_hashes.json C:\dest           # 크기 전수 + 표본 해시 -> ALL MATCH
```

## 이번 디스크에서 알게 된 것

- 컨테이너 시작은 표준 위치(LBA 409640)가 아니라 **LBA 53248**이었다. 409640에는 더 예전 포맷의 유효한 NXSB가 남아 있어 속았다. 디스크 끝에 남은 옛 GPT 엔트리 잔해와, 파일 시그니처 대조(300/300)로 확정.
- 폰 포맷은 앞 ~31MiB만 덮었다(NXSB·체크포인트 소실). FS-tree 노드는 컨테이너 앞 ~18GiB에 몰려 있었고 파일 데이터는 온전했다.
- 여기 하드코딩된 값(`START = 53248*512`, `/dev/rdisk4`, 경로)은 이 디스크 기준이다.
- macOS 27의 `gpt`는 `show`/`help` 외 쓰기 명령을 모두 거부한다(`operation not permitted`). 빈 공간에 복구용 파티션을 만들 땐 `sgdisk -g -o -n 1:<start>:<end> -t 1:AF0A`를 썼고, 1TB 희소 복제본으로 먼저 바뀌는 섹터를 확인했다(앞 3개 + 끝 2개).
- EX400U 펌웨어 FW91.0은 USB4/TB 모드에서 깨어나지 못하는 버그가 있다(Corsair 공지). USB 모드로만 읽었다. 고치는 Reinitialization Tool은 디스크를 전부 지운다.
