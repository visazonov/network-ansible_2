# network-ansible

Локальный путь:

```
\\wsl$\Ubuntu\home\hybridpc\network-ansible
```

В WSL: `/home/hybridpc/network-ansible`

Открыть папку: File → Open Folder… → вставить путь выше. Файлы править и сохранять там же.

Секреты: скопировать `.env.example` → `.env`. Лаба Arista (`arista_lab`): `ANSIBLE_USER_LAB`, `ANSIBLE_PASSWORD_LAB`, при необходимости `ANSIBLE_BECOME_PASSWORD_LAB`. Лаба Junos (`juniper_lab`): `JUNOS_USER`, `JUNOS_PASSWORD` (если пусто — `ANSIBLE_*_LAB`). Прод Arista и Junos (`arista_prod`, `juniper_prod`): одна LDAP-пара `ANSIBLE_USER`, `ANSIBLE_PASSWORD`. Restore из GitLab: `GITLAB_BACKUP_TOKEN`. Файл `.env` в git не класть.

Хосты и способ подключения — `inventory.ini`. Имя в `target_hosts` должно совпадать с именем в inventory.

## Сборка

Из этой папки:

```bash
docker compose build ansible
```

Либо:

```bash
docker compose build
```

После смены `Dockerfile` / `requirements.txt` образ пересобрать.

## Запуск

```bash
docker compose run --rm ansible playbooks/vlan_ensure.yml
docker compose run --rm ansible playbooks/config_restore.yml
```

Первый прогон соберёт образ, если ещё не собран. Сервис в Compose называется `ansible` — это имя сервиса, не команда Ansible.

## Что править

Плейбуки не трогать без нужды. Данные job — YAML в `vars/`. Хост без строки в `inventory.ini` в play не попадёт. Закомментированные строки (`#`) в списки не входят.

### `playbooks/vlan_ensure.yml`

**Что делает:** обеспечивает VLAN на устройствах из `target_hosts`. На Arista EOS — VLAN id и имя (`merged`, остальной конфиг не затирается). На Junos — IRB, unit на IFD, bridge-domain в `lan-l2`, привязку `irb` к `lan` и при необходимости prefix-list. Cisco IOS в роли пока не реализован.

**Как работает:** читает `vars/vlan_ensure.yml`. Плей идёт по группам `arista_eos`, `cisco_ios`, `juniper_junos`. Хост не из `target_hosts` — `end_host`. Дальше роль `vlan`: по `ansible_network_os` подключается свой tasks-файл.

- EOS: из каждого элемента `vlans` на свитч уходят только `vlan_id` и `name` (`eos_vlans`, `state: merged`). Поля `irb_address` / `network` / `prefix_lists` EOS не видит.
- Junos: шаблон `roles/vlan/templates/junos_add_vlan.set.j2` строит `set`-команды для всех `vlans`, один `junos_config` (NETCONF :830), `commit confirmed` (минуты заданы в роли). Пустой `prefix_lists: []` — только L2/L3, без policy-options. Непустой список — для каждой VLAN нужен `network`. Имена prefix-list задаются в YAML, шаблон не хардкодит `NAT` / `lan-msk-export`.

На EOS и Junos в одном запуске — два независимых канала (SSH CLI и NETCONF). Общего commit нет: один вендор может пройти, второй упасть.

**С нашей стороны:** править `vars/vlan_ensure.yml`.
- Кого трогать: блок `target_hosts` (имена как в `inventory.ini`).
- Какие VLAN: блок `vlans` — `vlan_id`, `name`; для Junos ещё `irb_address`, при prefix-list — `network` и `prefix_lists`.
- Junos IFD и RI (на все VLAN job): `vlan_access_if_by_host` (access IFD по имени хоста из inventory), `vlan_interfaces` (первый элемент — подстановка из карты, дальше общий LAG, сейчас `ae0`), `l3_instance`, `l2_instance`. Новый Junos-хост — строка в карте, иначе роль упадёт на assert.
- Новый VLAN — элемент с `-` на том же уровне, не внутрь предыдущего.

Затем:

```bash
docker compose run --rm ansible playbooks/vlan_ensure.yml
```

Junos: routing-instance `lan` и `lan-l2` на ящике уже должны быть. `confirm` на MX нужно подтвердить обычным `commit` до истечения таймера, иначе откат.

**Предупреждение:** не гонять `vlan_ensure` несколько раз подряд по Junos. Первый прогон делает `commit confirmed`: конфиг активен, но без подтверждающего `commit` на ящике через N минут **откатывается** (`via other` в `show system commit`). Повторный прогон playbook **пока таймер ещё тикает** Junos считает подтверждением pending commit (в том числе при `changed=0`) — откат уже не случится. Сначала дождаться окна или явно `commit` / `rollback` на MX, потом снова Ansible.

### `playbooks/config_restore.yml`

**Что делает:** подменяет **весь** running-config на Arista файлом из GitLab (`replace: config`). Не merge. Cisco — заглушка. Junos в этот плейбук не входит.

**Как работает:** читает `vars/config_restore.yml`. Хосты те же группы EOS/IOS, фильтр `target_hosts`. На контроллере (контейнер) клонирует `gitlab_backup_repo` (ветка `gitlab_backup_ref`) по HTTPS с `GITLAB_BACKUP_TOKEN`. Файл в клоне — `backup_relpath` (сейчас `US/{{ inventory_hostname }}/running-config.cfg`, регистр пути как в GitLab: `US` ≠ `us`). Снимает текущий running в `files/pre_restore/<хост>.pre-restore.cfg` (в git не коммитится). Затем полный replace. Эталон для лабы — дамп **vEOS**, не hardware 7050 (`Ethernet49` без `/1`).

**С нашей стороны:** править `vars/config_restore.yml` — `target_hosts`, при смене репо/ветки/пути к файлу — `gitlab_backup_repo`, `gitlab_backup_ref`, `backup_relpath`. Сам cfg класть в GitLab (проект `backup_for_eve`). Токен — в `.env`. Затем:

```bash
docker compose run --rm ansible playbooks/config_restore.yml
```

Не гонять restore прод-дампом 7050 на vEOS: SSH может выжить, CLI — уйти в timeout.

### Формат записей

VLAN (`vlans` в `vars/vlan_ensure.yml`):

```yaml
  - vlan_id: 20
    name: ansible-test-20
    irb_address: 10.83.0.101/24
    network: 10.83.0.0/24
    prefix_lists:
      - lan-msk-export
      - NAT
```

Только L2/L3 на Junos, без NAT/BGP:

```yaml
  - vlan_id: 21
    name: ansible-test-21
    irb_address: 10.83.4.101/24
    prefix_lists: []
```

Restore (`vars/config_restore.yml`):

```yaml
target_hosts:
  - leaf412
gitlab_backup_repo: https://gitlab.hybrid.ai/network/backup_for_eve.git
gitlab_backup_ref: master
backup_relpath: "US/{{ inventory_hostname }}/running-config.cfg"
```

Новый элемент списка — с `-` на том же уровне, что соседние записи. Закомментированные строки плейбук игнорирует.
