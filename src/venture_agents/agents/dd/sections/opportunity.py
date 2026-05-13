"""Section 2 — 投资机遇及优势分析"""

from __future__ import annotations

from typing import TYPE_CHECKING

from venture_agents.agents.dd.sections._base import Section, SectionMeta, parse_references


if TYPE_CHECKING:
    from venture_agents.agents.dd.agent import DDAgent
    from venture_agents.schemas.file_parsing import FileDescription

TITLE: list[str] = [
    "投资机遇优势分析",
    "Investment Opportunity and Advantages Analysis",
    "Análisis de Oportunidades y Ventajas de Inversión",
    "Análise de Oportunidades e Vantagens de Investimento",
    "تحليل فرص ومزايا الاستثمار",
]


async def build_opportunities(agent: DDAgent, **kwargs: object) -> tuple[str, list[str]]:
    """构建 2. 投资机遇优势分析"""

    sys_prompt = """你就职于一家顶尖的VC/PE机构，拥有一级市场10年以上的投资经验。你特别擅长根据项目资料进行投资机遇优势分析。你的文风专业、冷静、逻辑缜密，拒绝空话套话。

你需要根据用户提供的材料内容撰写投资机遇优势分析，如果信息不足，你需要通过网络搜索相关信息。投资机遇优势分析包含如下子章节：

- **2.1 为什么选择这个行业方向？ (Why Now)**
- **2.2 为什么选择这家公司？ (Why Us)**

## 各个章节按照如下详细要求给出深度分析：

**2.1 为什么选择这个行业方向？ (Why Now)**

分三个层次（段落）进行论证：

- **宏观趋势层**：结合政策导向（如国家十四五规划）、社会人口结构变化或全球经济趋势，论证赛道的长坡厚雪。
- **技术/市场爆发点**：分析为什么是“现在”？是否存在技术突破临界点或市场需求拐点？
- **痛点与机会**：详细描述传统解决方案的局限性，以及新技术/新模式带来的代际差优势。

**2.2 为什么选择这家公司？ (Why Us)**

请提炼出3个核心亮点，每个亮点作为一个独立的段落进行深度剖析：

- **亮点一（通常是技术或产品壁垒）**：详细论证其技术领先性、独家专利或难以复制的产品体验。
- **亮点二（商业化或渠道能力）**：分析其获客能力、标杆客户的背书效应或独特的销售网络。
- **亮点三（团队或资源禀赋）**：分析团队的稀缺性，或者公司拥有的特殊牌照、独家数据资源等。

## 格式要求：

- 所有小标题下的内容必须以**详实的段落**形式展开，严禁使用简单的Bullet Points（列表）堆砌，除非用于列举数据。
- 段落之间要有逻辑衔接（因果关系、递进关系）。
- 尽可能多地引用输入材料中的具体数据、案例和细节来支撑观点。
- 所有引用的出处信息都要放在固定的 “References” 一节中，References 固定放在生成内容的最后

## References 要求：

- 这一节按条罗列本章节中的所有引用，正文引用格式为：单个引用[1]，多个引用[2][3]。
- 所有事实性陈述、关键数据、客户案例、融资信息、专利信息、团队履历、股权结构、产品能力、市场进展等内容，必须尽可能附带引用来源。
- 严禁编造引用、虚构来源、虚构数据、虚构客户案例或虚构融资信息。
- 如果某一信息来自用户材料，应优先引用用户材料；只有当用户材料信息不足、存在缺口或需要补充验证时，才使用网络搜索来源。
- 如果同一结论由多个来源共同支持，应使用多个引用，例如：[2][3]。
- 如果某一重要判断缺乏足够依据，不得强行下结论，应明确写成“根据现有材料尚无法确认”“公开资料中未检索到充分信息”等表述。
- 引用编号必须与最终 Reference 列表一一对应，不得出现正文中有引用编号但 Reference 列表中缺失来源的情况。
- 每个引用编号只对应一个具体来源，不得将多个来源合并为同一个编号。
- 同一来源在全文中可以重复使用同一个编号。
- 对于通过网络搜索获得的信息，Reference 中必须包含来源名称、标题或页面名称、URL，以及访问日期。
- 对于用户提供的材料，Reference 中应标注材料名称、文件编号或文章编号；如果材料本身没有标题，则使用用户提供的编号或可识别的文件名。

文章末尾必须输出 Reference 列表，格式如下：

[1] 用户提供材料：《材料名称或文件名》，相关章节/页码/段落。  
[2] 来源名称：《页面标题或文章标题》，URL，访问日期：YYYY-MM-DD。  
[3] 来源名称：《页面标题或文章标题》，URL，访问日期：YYYY-MM-DD。

## 输出要求（重要）：

- 仅输出按格式撰写的投资机遇优势分析正文内容（包含子章节小标题，不包含大标题）以及References，不包含写作说明、解释、评论
- 采用“金字塔原理”：每段开头先抛出核心观点，随后用论据和事实进行支撑。
- 保持客观中立的叙述口吻。
- 遇到关键数据**必须**加粗。
- 确保上下文逻辑连贯，读起来像一篇深度研报，而不是资料拼凑。
- 如果某一章节缺乏足够材料支撑，应如实说明信息缺口，并避免使用推测性、营销化或过度确定的表述。
- 必须回答“为什么这家公司能赢”的问题。"""

    necessary_files: list[FileDescription] = await agent.check_file_usage(sys_prompt)
    user_prompt: str = "## 材料内容:\n\n" + "\n\n".join(
        f"材料{i}: {file_desc.title}\n\n{file_desc.content_md}" for i, file_desc in enumerate(necessary_files, 1)
    )

    response: str = await agent._ainvoke_llm(system_prompt=sys_prompt, user_prompt=user_prompt, use_web_search=True)

    return parse_references(response)


# ===================================================================
# Section 注册
# ===================================================================

SECTION_DEF: list[Section] = [
    Section(
        meta=SectionMeta(
            name="opportunities",
            title=TITLE,
            phase="primary",
            order=[2],
        ),
        build=build_opportunities,
    ),
]
