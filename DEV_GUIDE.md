# VentureAgents项目开发指南

## 1. 文档概述

### 1.1 核心目标
- **明确项目架构**：统一规定代码、测试、脚本、文档等各部分的位置
- **统一代码风格**：通过工具自动格式化，消除团队内部代码风格争议
- **质量门禁前置**：在开发阶段发现类型错误、语法问题和潜在Bug
- **测试驱动开发**：建立可量化的质量指标，确保代码可靠性
- **提升协作效率**：减少Code Review负担，聚焦业务逻辑而非格式细节

### 1.2 标准化工具链定位

| 工具       | 作用               | 定位                           |
| ---------- | ------------------ | ------------------------------ |
| **Black**  | 代码格式化         | 强制执行不可配置的代码风格     |
| **Ruff**   | 代码质量检查与修复 | 替代flake8+isort，极速静态分析 |
| **Mypy**   | 静态类型检查       | 渐进式类型安全                 |
| **Pytest** | 单元测试框架       | 测试驱动开发与覆盖率验证       |

**核心理念**：格式、规范、类型、测试全部自动化；开发者专注业务逻辑实现

## 2. 项目架构

### 2.1 整体架构

```text
Agents
    |
Tools Layer
    |
Schema Layer
    |
Data / Network Layer
````

### 2.2 架构设计原则

* 单一职责（SRP）
* 模块解耦，接口清晰
* 可测试、可扩展
* 避免业务逻辑散落在 Controller / Script 中

### 2.3 技术栈

| 类型    | 技术                               |
| ----- | -------------------------------- |
| 语言    | Python        |
| 框架    | Multi-agnet with MCP  |
| 数据库   | ChromaDB      |
| 数据处理 | 自研Data Pipeline工具库 |
| 语言模型 | GPT-4o / Qwen3-max |
| 测试    | Pytest                    |
| CI/CD | GitHub Actions                   |
| 代码规范  | Black / Ruff / Mypy / Pytest            |

### 2.4 目录结构

```text
VentureAgents
├── src/venture_agents/
│   ├── __init__.py                         # 包入口
│   ├── agents/                             # Agent 层
│   │   ├── __init__.py
│   │   ├── base.py                         # Agent 抽象基类（共享）
│   │   └── dd/                             # DD Agent
│   ├── tools/                              # 工具层（共享）
│   │   ├── __init__.py
│   │   ├── base.py                         # Tool 抽象基类
│   │   └── ...
│   ├── schemas/                            # 数据类型定义（共享）
│   └── utils/                              # 工具函数（共享）
├── tests/                                  # 单元测试 / 集成测试
├── scripts/                                # 运维 / 本地脚本
├── docs/                                   # 设计文档
├── .github/                                # GitHub Actions / 模板
├── README.md
├── DEV_GUIDE.md                            # 开发规范说明
├── pyproject.toml                          # 项目配置
└── .pre-commit-config.yaml                 # pre-commit配置
```

`src/venture_agents/`目录应该按照Python Package的方式组织：`src/venture_agents/`以及其包含的每个子目录都应该包含`__init__.py`以及对应的代码文件。

## 3. 环境准备与安装

### 3.1 版本要求
- **Python版本**：≥ 3.12
- **虚拟环境**：必须使用（防止包冲突）

### 3.2 安装方案
在根目录执行下述操作：
- 将本地代码注册到Python import system中并安装依赖
  ```bash
  pip install -e ".[dev]"
  ```
  如果是部署环境，则不需要`[dev]`：
  ```bash
  pip install -e ".[agents-all]"
  ```
  完成注册之后，项目中任意代码都可以引用到`src/venture_agents/`中的其他代码。例如：
  ```python
  from venture_agents.agents.dd.agent import DDAgent
  ```
  就可以加载`src/venture_agents/agents/dd/agent.py`中的`DDAgent`类。

### 3.3 最小化安装依赖

项目产出一个wheel安装包：`venture_agents-x.y.z-py3-none-any.whl`，在生产环境中，根据所需功能安装依赖项，减少不必要依赖带来的空间开销。

例如，只需要安装DDAgent相关功能，可以使用如下命令安装：
```shell
pip install "venture_agents-x.y.z-py3-none-any.whl[dd]"
```

## 4. 配置文件

- 项目根目录的`pyproject.toml`文件规定了当前项目的规范化配置。
- 根目录`.pre-commit-config.yaml`文件规定了commit和push前的检查项
- `.github/workflows/ci.yml`文件规定了GitHub CI流程
- 运行时项目配置使用`config.yaml`（本地文件不提交），结构定义在`src/venture_agents/schemas/config.py`，加载入口为`venture_agents.utils.config.get_settings()`。

### 4.1 运行时配置

可参考根目录`config.example.yaml`创建本地`config.yaml`。配置加载完成后会返回嵌套的Pydantic对象：

```python
from venture_agents.utils.config import get_settings

settings = get_settings()
model = settings.llm.chat.model
proxy = settings.llm.openai.proxy
```

敏感信息推荐使用环境变量：

```bash
export OPENAI_API_KEY="sk-..."
```

### 4.2 Pre-commit配置
配置文件参见根目录`.pre-commit-config.yaml`

安装pre-commit：
```bash
pre-commit install
pre-commit install --hook-type pre-push
```

## 5. 核心工具使用

### 5.1 Black - 代码格式化
```bash
# 格式化所有文件
black .

# 检查格式（CI使用）
black --check .

# 查看格式化差异
black --diff .

# 格式化指定目录
black src/ tests/
```

### 5.2 Ruff - 代码质量检查与修复
```bash
# 仅检查（不修复。推荐这么做，自己手动修改）
ruff check .

# 检查并修复所有问题
ruff check --fix .

# 只看改动，不直接写入（参考Ruff的修改建议）
ruff check . --fix --diff

# 检查特定规则
ruff check --select E,F .

# 查看规则详情
ruff rule E501

# 仅检查git暂存文件
ruff check $(git diff --name-only --cached -- '*.py')
```

### 5.3 Mypy - 静态类型检查
```bash
# 检查所有代码
mypy .

# 检查指定模块
mypy src/ tests/

# 生成HTML报告
mypy --html-report mypy-report .

# 按实际依赖安装缺少的类型存根
pip install types-xxx
```

### 5.4 Pytest - 测试执行
```bash
# 运行所有测试并检查覆盖率
pytest

# 运行特定测试
pytest tests/unit/
pytest tests/test_user.py::TestUser::test_create_user

# 仅运行失败的测试
pytest --lf

# 运行标记的测试
pytest -m "not slow"

# 生成覆盖率报告
pytest --cov=venture_agents --cov-report=html
```

### 5.5 本地开发流程
```bash
# 完整开发循环
1. 编写代码
2. black .               # 格式化
3. ruff check --fix .    # 自动修复
4. mypy .               # 类型检查
5. pytest               # 运行测试
6. git add .
7. git commit
```

## 6. 编辑器/IDE集成

### 6.1 VS Code 集成
#### 步骤 1：安装插件
- Python（微软官方，已包含Pytest）
- Ruff（Astral官方）
- Black Formatter（微软官方）

**注意：** 不推荐使用独立的Mypy插件，目前独立的Mypy插件不稳定。

#### 步骤 2：配置 settings.json
打开 `File > Preferences > Settings`，右上角打开 JSON 配置，添加：
```json
{
  // =====================================================
  // Black —— 只做格式化，规则来自 pyproject.toml
  // =====================================================
  "editor.formatOnSave": true,
  "[python]": {
      "editor.defaultFormatter": "ms-python.black-formatter"
  },
  // =====================================================
  // Ruff —— Lint + Fix + Import 排序
  // =====================================================
  // Ruff 插件配置
  "ruff.enable": true,
  // 保存时自动修复（与你的 fix=true 完美契合）
  "editor.codeActionsOnSave": {
      "source.fixAll.ruff": true,
      "source.organizeImports.ruff": true
  },
  // =====================================================
  // Pytest —— VS Code 内建支持
  // =====================================================
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  // 让 pytest 自行读取 pyproject.toml
  "python.testing.pytestArgs": [],
  "python.testing.pytestPath": "pytest",
  // 自动发现测试
  "python.testing.autoTestDiscoverOnSaveEnabled": true,
}
```

### 6.2 PyCharm 集成
#### 步骤 1：安装插件
- Black（搜索 `Black` 插件并安装）
- Ruff（搜索 `Ruff` 插件并安装）

#### 步骤 2：配置 Black
- `File > Settings > Tools > Black`：勾选 `Enable Black`，配置路径为虚拟环境下的 `bin/black`（macOS/Linux）或 `Scripts/black.exe`（Windows），设置 `Line length` 为 88。
- `File > Settings > Tools > Actions on Save`：勾选 `Reformat code`（使用Black自动格式化）。

#### 步骤 3：配置 Ruff
- `File > Settings > Tools > Ruff`：勾选 `Enable Ruff`，配置路径为虚拟环境下的 `bin/ruff` 或 `Scripts/ruff.exe`，勾选 `Run Ruff on save`。

#### 步骤 4：配置 Mypy
- `File > Settings > Project > Python Interpreter`：确保已安装 `mypy`。
- `File > Settings > Tools > Mypy`：勾选 `Enable mypy`，配置路径为虚拟环境下的 `bin/mypy` 或 `Scripts/mypy.exe`，添加参数 `--config-file pyproject.toml`。

#### 步骤 5：配置 Pytest
- `File > Settings > Tools > Python Integrated Tools > Testing`：选择 `pytest`，配置路径为虚拟环境下的 `bin/pytest` 或 `Scripts/pytest.exe`。
- 右键 `tests` 目录 > `Run 'pytest in tests'`，在运行配置中添加参数 `--cov=venture_agents --cov-fail-under=80`。


## 7. 测试规范

### 7.1 目录结构
```
project/
├── src/
│   ├── __init__.py
│   ├── module1/
│   ├── module2/
│   └── ...
└── tests/
    ├── unit/              # 单元测试
    │   ├── module1/       # module1对应的单元测试
    │   ├── module2/       # module2对应的单元测试
    │   └── ...
    └── integration/       # 集成测试
```

### 7.2. 命名规则
- 测试文件：`test_*.py` 或 `*_test.py`
- 测试类：`Test*`（如 `TestMathUtils`）
- 测试函数：`test_*`（如 `test_add_two_numbers`）

### 7.3. 用例编写规范
#### （1）单一职责
每个测试用例只验证一个功能点，避免多断言（参数化测试除外）。

#### （2）参数化测试
用 `@pytest.mark.parametrize` 处理多组输入：
```python
import pytest
from venture_agents.utils.math import calculate_sum

@pytest.mark.parametrize("numbers, expected", [
    ([1, 2, 3], 6),
    ([], 0),
    ([-1, -2], -3),
])
def test_calculate_sum(numbers, expected):
    assert calculate_sum(numbers) == expected
```

#### （3）夹具（Fixture）复用
在 `conftest.py` 中定义全局夹具：
```python
# tests/conftest.py
import pytest

@pytest.fixture
def test_user_id():
    return 1  # 复用的测试数据
```
测试中使用：
```python
def test_get_user_name(test_user_id):
    from venture_agents.main import get_user_name
    assert get_user_name(test_user_id) == "admin"
```

#### （4）Mock 外部依赖
用 `pytest-mock` 模拟数据库、接口等外部服务：
```python
def test_call_external_api(mocker):
    # 模拟requests.get返回值
    mock_get = mocker.patch("venture_agents.main.requests.get")
    mock_get.return_value.status_code = 200

    from venture_agents.main import call_external_api
    assert call_external_api() == 200
```

### 7.4 覆盖率要求
- **新功能**：覆盖率必须≥85%
- **核心模块**：覆盖率必须≥90%
- **边界条件**：必须覆盖正常、异常、边界场景
- **排除范围**：配置、常量、类型定义可排除

## 8. 团队协作规范

### 8.1 类型注解规范
```python
# 当前Python版本约束在3.12+，进行类型定义尽量不要依赖typing模块，除了没有内置的类型
from typing import Any
from dataclasses import dataclass

@dataclass
class User:
    id: int
    name: str
    email: str | None = None

# Python 3.9+ 可使用内置泛型
def process_data(data: dict[str, int]) -> list[str]:
    return [str(v) for v in data.values()]

# 注意：尽量不要使用老式的List/Dict这种类型提示
def process_users(users: List[User]) -> Dict[int, str]:
    """处理用户列表，返回ID到名称的映射"""
    return {user.id: user.name for user in users}
```

### 8.2 规则忽略规范
```python
# 1. 临时调试（修复后必须删除）
print("调试信息")  # noqa: T201

# 2. 第三方库无类型注解
import some_library  # type: ignore[import]

# 3. Black无法处理的特殊情况
# fmt: off
special_format = {
    "key1": "value1",
    "key2": "value2",
}
# fmt: on

# 4. 测试跳过（需注明原因）
@pytest.mark.skip(reason="依赖服务维护中，预计2024-12-31恢复")
def test_external_service():
    ...
```

## 九、故障排查指南

### 9.1 常见问题解决方案

| 问题                            | 原因               | 解决方案                                                     |
| ------------------------------- | ------------------ | ------------------------------------------------------------ |
| **Mypy: Missing library stubs** | 第三方库无类型注解 | 1. `pip install types-xxx`<br>2. 临时: `# type: ignore[import]`<br>3. 长期: 提交PR添加类型注解 |
| **Black与Ruff冲突**             | 配置不一致         | 确保`pyproject.toml`中`line-length`值相同                    |
| **Pytest覆盖率不达标**          | 测试覆盖不全       | 1. 查看HTML报告<br>2. 补充测试用例<br>3. 调整`fail_under`阈值 |
| **Ruff修复无效**                | 规则不可自动修复   | 手动修复或添加`# noqa: [规则代码]`                           |
| **Import排序问题**              | Ruff与isort冲突    | 使用Ruff内置的isort，删除单独isort配置                       |
| **测试Mock失败**                | Mock路径错误       | 使用被测试模块中的实际导入路径                               |

### 9.2 渐进式迁移策略
1. **新项目**：直接使用完整配置
2. **旧项目迁移**：
   - 阶段1：仅对新文件应用规范
   - 阶段2：逐步添加类型注解
   - 阶段3：分批格式化旧代码
   - 阶段4：补充测试，提升覆盖率

### 9.3 紧急绕过机制
```bash
# 紧急提交（绕过所有检查）
git commit --no-verify -m "紧急修复: [问题描述]"

# 临时降低覆盖率要求
pytest --cov=venture_agents --cov-fail-under=70

# 忽略特定Mypy错误
mypy --disable-error-code [error-code] .
```

### 9.4 调试复杂测试
- 如果你经常 debug 复杂失败，可在本地的配置文件中的Pytest配置项`addopts`中将
  > --tb=short

  **【临时】** 覆盖为

  > --tb=long

## 十、附录：命令速查表

| 场景           | 命令                                                   | 说明                     |
| -------------- | ------------------------------------------------------ | ------------------------ |
| **完整检查**   | `black . && ruff check --fix . && mypy . && pytest`    | 开发全流程               |
| **仅格式化**   | `black .`                                              | 格式化所有文件           |
| **代码修复**   | `ruff check --fix .`                                   | 自动修复可修复问题       |
| **类型检查**   | `mypy src/ tests/`                                     | 静态类型检查             |
| **运行测试**   | `pytest -xvs`                                          | 详细输出，遇到失败即停止 |
| **覆盖率**     | `pytest --cov=venture_agents --cov-report=html`        | 生成HTML报告             |
| **pre-commit** | `pre-commit run --all-files`                           | 手动运行所有钩子         |
| **清理缓存**   | `find . -type d -name "__pycache__" -exec rm -rf {} +` | 清理Python缓存           |

## 十一、参考资源
- **Black文档**: https://black.readthedocs.io/
- **Ruff文档**: https://docs.astral.sh/ruff/
- **Mypy文档**: https://mypy.readthedocs.io/
- **Pytest文档**: https://docs.pytest.org/
- **PEP 8**: https://peps.python.org/pep-0008/
- **Python类型注解**: https://docs.python.org/3/library/typing.html

## 十二、版本维护
- **工具版本**：每季度评估并更新工具链版本
- **配置同步**：所有项目共用配置模板：
  - `pyproject.toml`
  - `.pre-commit-config.yaml`
  - `.github/workflows/ci.yml`
- **规范评审**：每半年回顾并更新团队规范
