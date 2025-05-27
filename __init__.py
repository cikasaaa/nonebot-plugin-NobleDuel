import json
import random
from pathlib import Path
from typing import Dict, List, Optional
from nonebot import get_driver, require , logger , get_bot
from nonebot.plugin import on_message, PluginMetadata
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot_plugin_alconna import Alconna, on_alconna, UniMessage, Args , AlcResult , At
from nonebot_plugin_localstore import get_data_file
from nonebot_plugin_apscheduler import scheduler
from datetime import datetime
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment, GROUP_ADMIN, GROUP_OWNER
from nonebot.adapters.onebot.v11 import Bot
__plugin_meta__ = PluginMetadata(
    name="贵族决斗",
    description="一个基于QQ的贵族决斗小游戏，支持爵位、女友、决斗等功能",
    usage="发送“帮助”查看所有指令",
)

# 数据文件路径
DATA_PATH = Path(r"M:\ALL BOT PROGRAM\3099632897-FUNCTION\mikubot\src\plugins\guizujuedou") / "data.json"

# 常量定义
GIFTS = {
    "玩偶": {"affection": 5, "cost": 10},
    "礼服": {"affection": 10, "cost": 20},
    "歌剧门票": {"affection": 15, "cost": 30},
    "水晶球": {"affection": 20, "cost": 40},
    "耳环": {"affection": 25, "cost": 50},
    "发饰": {"affection": 30, "cost": 60},
    "小裙子": {"affection": 35, "cost": 70},
    "热牛奶": {"affection": 40, "cost": 80},
    "书": {"affection": 45, "cost": 90},
    "鲜花": {"affection": 50, "cost": 100},
}

TOOLS = {
    "手铐": {"effect": "skip_turn", "cost": 50},
    "酒": {"effect": "increase_damage", "cost": 30},
    "饮料": {"effect": "heal", "cost": 20},
    "刀": {"effect": "direct_damage", "cost": 40},
}

TITLES = [
    {"name": "男爵", "prestige": 500, "gf_limit": 5},
    {"name": "子爵", "prestige": 1000, "gf_limit": 10},
    {"name": "伯爵", "prestige": 2000, "gf_limit": 15},
    {"name": "侯爵", "prestige": 3000, "gf_limit": 20},
    {"name": "公爵", "prestige": 4000, "gf_limit": 25},
    {"name": "国王", "prestige": 5000, "gf_limit": 30},
]

# 生成 200 个女友名字
chinese_chars = ["小", "大", "明", "华", "丽", "平", "军", "静", "强", "美", "芳", "国", "玉", "兰", "香", "月", "花", "雨", "雪", "风"]

def generate_girlfriends_pool() -> List[str]:
    pool = set()
    while len(pool) < 200:
        length = random.randint(1, 4)
        name = "".join(random.choice(chinese_chars) for _ in range(length))
        pool.add(name)
    return list(pool)

# 数据读写
def load_data() -> Dict:
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"groups": {}}

def save_data(data: Dict):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 获取用户当前爵位
def get_user_title(prestige: int) -> Dict:
    for title in reversed(TITLES):
        if prestige >= title["prestige"]:
            return title
    return TITLES[0]

# 初始化群数据
def init_group_data(data: Dict, group_id: str):
    if group_id not in data["groups"]:
        data["groups"][group_id] = {
            "users": {},
            "duels": {},
            "girlfriends_pool": generate_girlfriends_pool(),
            "duel_count": {}  # 每日决斗次数
        }
    save_data(data)

# 定时任务：每日午夜重置签到状态和决斗次数
@scheduler.scheduled_job("cron", hour=0, minute=0)
async def midnight_reset():
    data = load_data()
    for group in data["groups"].values():
        for user in group["users"].values():
            user["has_checked_in_today"] = False
        group["duel_count"] = {}  # 重置每日决斗次数
    save_data(data)

# 命令定义
create_noble_cmd = Alconna("创建贵族")
create_noble_matcher = on_alconna(create_noble_cmd)

@create_noble_matcher.handle()
async def handle_create_noble(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    init_group_data(data, group_id)
    if user_id in data["groups"][group_id]["users"]:
        await create_noble_matcher.finish("您已经是贵族啦！不能重复创建！")
    else:
        data["groups"][group_id]["users"][user_id] = {
            "is_noble": True,
            "gold": 1000,
            "prestige": 500,
            "title": "男爵",
            "girlfriends": [],
            "items": {"gifts": {k: 0 for k in GIFTS}, "tools": {k: 0 for k in TOOLS}},
            "has_checked_in_today": False
        }
        save_data(data)
        await create_noble_matcher.finish("贵族创建成功！您现在是一名男爵，祝您好运！")

noble_query_cmd = Alconna("贵族查询")
noble_query_matcher = on_alconna(noble_query_cmd)

@noble_query_matcher.handle()
async def handle_noble_query(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await noble_query_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    title = user_data["title"]
    prestige = user_data["prestige"]
    gold = user_data["gold"]
    gf_count = len(user_data["girlfriends"])
    await noble_query_matcher.finish(
        f"您当前的爵位是：{title}\n"
        f"您当前拥有{prestige}声望\n"
        f"您当前持有{gold}金币\n"
        f"您当前拥有{gf_count}个女友"
    )

checkin_cmd = Alconna("贵族签到")
checkin_matcher = on_alconna(checkin_cmd)

@checkin_matcher.handle()
async def handle_checkin(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await checkin_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    if user_data.get("has_checked_in_today", False):
        await checkin_matcher.finish("您今天已经签到过了，明天再来吧！")
    else:
        reward = random.randint(400, 600)
        user_data["gold"] += reward
        user_data["prestige"] += reward
        user_data["has_checked_in_today"] = True
        save_data(data)
        await checkin_matcher.finish(f"签到成功，今日奖励{reward}金币和{reward}声望")

date_cmd = Alconna("贵族约会")
date_matcher = on_alconna(date_cmd)

@date_matcher.handle()
async def handle_date(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await date_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    title = get_user_title(user_data["prestige"])
    gf_limit = title["gf_limit"]
    if len(user_data["girlfriends"]) >= gf_limit:
        await date_matcher.finish(f"您的女友数量已达上限（{gf_limit}），升级爵位可增加上限！")
    if user_data["gold"] < 300:
        await date_matcher.finish("您目前的金币数量不足，可以通过每日签到和贵族决斗来获取金币")
    available_gfs = [gf for gf in data["groups"][group_id]["girlfriends_pool"] if gf not in [g["name"] for g in user_data["girlfriends"]]]
    if not available_gfs:
        await date_matcher.finish("女友池已空，暂时无法招募新女友！")
    gf_name = random.choice(available_gfs)
    user_data["gold"] -= 300
    user_data["girlfriends"].append({"name": gf_name, "affection": 0})
    save_data(data)
    await date_matcher.finish(f"约会成功！您的新女友是{gf_name}！")

upgrade_title_cmd = Alconna("升级爵位")
upgrade_title_matcher = on_alconna(upgrade_title_cmd)

@upgrade_title_matcher.handle()
async def handle_upgrade_title(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await upgrade_title_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    current_prestige = user_data["prestige"]
    current_title = get_user_title(current_prestige)
    next_title = None
    for title in TITLES:
        if title["prestige"] > current_prestige and (not next_title or title["prestige"] < next_title["prestige"]):
            next_title = title
    if not next_title or current_prestige >= current_title["prestige"]:
        if current_title["name"] == "国王":
            await upgrade_title_matcher.finish("您已是最高爵位国王，无需升级！")
        else:
            await upgrade_title_matcher.finish(f"很抱歉，您的声望目前还不够升级到下一个爵位，请努力加油获取声望吧")
    else:
        user_data["title"] = next_title["name"]
        save_data(data)
        await upgrade_title_matcher.finish(f"升级爵位成功，您目前的爵位是{next_title['name']}！")

gold_query_cmd = Alconna("查询金币")
gold_query_matcher = on_alconna(gold_query_cmd)

@gold_query_matcher.handle()
async def handle_gold_query(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await gold_query_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    await gold_query_matcher.finish(f"您当前持有{user_data['gold']}金币")

gf_count_cmd = Alconna("查询女友数量")
gf_count_matcher = on_alconna(gf_count_cmd)

@gf_count_matcher.handle()
async def handle_gf_count(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await gf_count_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    await gf_count_matcher.finish(f"您目前有{len(user_data['girlfriends'])}位女友")

gf_query_cmd = Alconna("查询女友", ["index:int"])
gf_query_matcher = on_alconna(gf_query_cmd)

@gf_query_matcher.handle()
async def handle_gf_query(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    index = alc_result.query("index")
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await gf_query_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    if index < 1 or index > len(user_data["girlfriends"]):
        await gf_query_matcher.finish("您尚未拥有该女友")
    gf = user_data["girlfriends"][index - 1]
    await gf_query_matcher.finish(f"该女友的名字为{gf['name']}，目前对他的好感度为{gf['affection']}")

affection_query_cmd = Alconna("好感度查询")
affection_query_matcher = on_alconna(affection_query_cmd)

@affection_query_matcher.handle()
async def handle_affection_query(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await affection_query_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    if not user_data["girlfriends"]:
        await affection_query_matcher.finish("您目前没有女友")
    msg = "您目前所有女友的好感度为：\n"
    for i, gf in enumerate(user_data["girlfriends"], 1):
        msg += f"{i}. {gf['name']}：{gf['affection']}\n"
    await affection_query_matcher.finish(msg)

gift_cmd = Alconna("礼物", ["gift_name:str", "gf_index:int"])
gift_matcher = on_alconna(gift_cmd)

@gift_matcher.handle()
async def handle_gift(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    gift_name = alc_result.query("gift_name")
    gf_index = alc_result.query("gf_index")
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await gift_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    if gift_name not in GIFTS:
        await gift_matcher.finish("无效的礼物名称")
    if user_data["items"]["gifts"].get(gift_name, 0) <= 0:
        await gift_matcher.finish("赠送失败，您尚未拥有该礼物")
    if gf_index < 1 or gf_index > len(user_data["girlfriends"]):
        await gift_matcher.finish("您尚未拥有该女友")
    gf = user_data["girlfriends"][gf_index - 1]
    user_data["items"]["gifts"][gift_name] -= 1
    gf["affection"] += GIFTS[gift_name]["affection"]
    save_data(data)
    await gift_matcher.finish(f"送礼成功，{gf['name']}对你增加了{GIFTS[gift_name]['affection']}好感")

breakup_cmd = Alconna("分手", ["gf_index:int"])
breakup_matcher = on_alconna(breakup_cmd)

@breakup_matcher.handle()
async def handle_breakup(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    gf_index = alc_result.query("gf_index")
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await breakup_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    if gf_index < 1 or gf_index > len(user_data["girlfriends"]):
        await breakup_matcher.finish("您尚未拥有该女友")
    if user_data["gold"] < 200:
        await breakup_matcher.finish("您的金币不足以支付分手费用（200金币）")
    user_data["gold"] -= 200
    gf = user_data["girlfriends"].pop(gf_index - 1)
    save_data(data)
    await breakup_matcher.finish("分手成功，扣除200金币")

buy_item_cmd = Alconna("购买道具", ["item_name:str"])
buy_item_matcher = on_alconna(buy_item_cmd)

@buy_item_matcher.handle()
async def handle_buy_item(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    item_name = alc_result.query("item_name")
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await buy_item_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    item_type = "gifts" if item_name in GIFTS else "tools" if item_name in TOOLS else None
    if not item_type:
        await buy_item_matcher.finish("无效的道具名称")
    cost = GIFTS[item_name]["cost"] if item_type == "gifts" else TOOLS[item_name]["cost"]
    if user_data["gold"] < cost:
        await buy_item_matcher.finish("很抱歉，您的金币不足，可以通过每日签到和贵族决斗来获取金币")
    user_data["items"][item_type][item_name] = user_data["items"][item_type].get(item_name, 0) + 1
    user_data["gold"] -= cost
    save_data(data)
    await buy_item_matcher.finish(f"购买成功，您目前持有该道具{user_data['items'][item_type][item_name]}个")

item_query_cmd = Alconna("道具查询")
item_query_matcher = on_alconna(item_query_cmd)

@item_query_matcher.handle()
async def handle_item_query(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await item_query_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    user_data = data["groups"][group_id]["users"][user_id]
    items = []
    for gift, count in user_data["items"]["gifts"].items():
        if count > 0:
            items.append(f"{gift} {count}个")
    for tool, count in user_data["items"]["tools"].items():
        if count > 0:
            items.append(f"{tool} {count}个")
    if not items:
        await item_query_matcher.finish("您尚未持有道具，可通过指令“购买道具 道具名”来购买道具")
    await item_query_matcher.finish("您当前持有的道具有：\n" + "\n".join(items))

duel_cmd = Alconna("贵族决斗", Args["opponent", At])
duel_matcher = on_alconna(duel_cmd)

@duel_matcher.handle()
async def handle_duel(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    opponent_id = alc_result.result.args.get("opponent").target if alc_result.result and alc_result.result.args.get("opponent") else None
    data = load_data()
    init_group_data(data, group_id)
    if group_id not in data["groups"] or user_id not in data["groups"][group_id]["users"]:
        await duel_matcher.finish("您还未在本群创建过贵族，请发送“创建贵族”开始您的贵族之旅。")
    if not opponent_id or opponent_id not in data["groups"][group_id]["users"]:
        await duel_matcher.finish("无效的对手，请@一名已创建贵族的玩家")
    if user_id == opponent_id:
        await duel_matcher.finish("不能与自己决斗！")
    user_data = data["groups"][group_id]["users"][user_id]
    opponent_data = data["groups"][group_id]["users"][opponent_id]
    if not user_data["girlfriends"] or not opponent_data["girlfriends"]:
        await duel_matcher.finish("双方必须至少拥有一位女友才能决斗")
    if data["groups"][group_id]["duels"]:
        await duel_matcher.finish("当前已经存在决斗，请先等待本次决斗结束")
    duel_count = data["groups"][group_id]["duel_count"].get(user_id, 0)
    if duel_count >= 10:
        await duel_matcher.finish("您今日的决斗次数已达上限（10次）")
    data["groups"][group_id]["duel_count"][user_id] = duel_count + 1
    duel_id = f"{user_id}_{opponent_id}_{int(datetime.now().timestamp())}"
    data["groups"][group_id]["duels"][duel_id] = {
        "player1": user_id,
        "player2": opponent_id,
        "health1": 6,
        "health2": 6,
        "used_items1": [],
        "used_items2": [],
        "turn": 1,
        "waiting_accept": True,
        "last_action_time": int(datetime.now().timestamp()),
        "current_player": user_id,
        "pending_tool": None
    }
    save_data(data)
    await duel_matcher.finish(
        MessageSegment.at(opponent_id) + " 决斗创建成功，请接受决斗玩家发送“接受决斗”或“拒绝决斗”，若30秒内无人接受挑战则此次对决作废"
    )

accept_duel_cmd = Alconna("接受决斗")
accept_duel_matcher = on_alconna(accept_duel_cmd)

@accept_duel_matcher.handle()
async def handle_accept_duel(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"]:
        await accept_duel_matcher.finish("当前没有进行中的决斗")
    duels = data["groups"][group_id]["duels"]
    duel_id = None
    for did, duel in duels.items():
        if duel["player2"] == user_id and duel.get("waiting_accept", False):
            duel_id = did
            break
    if not duel_id:
        await accept_duel_matcher.finish("您没有待接受的决斗")
    duel = duels[duel_id]
    duel["waiting_accept"] = False
    save_data(data)
    await accept_duel_matcher.finish("决斗开始，如果决斗出现bug请发送“重置决斗”结束该轮决斗")

reject_duel_cmd = Alconna("拒绝决斗")
reject_duel_matcher = on_alconna(reject_duel_cmd)

@reject_duel_matcher.handle()
async def handle_reject_duel(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"]:
        await reject_duel_matcher.finish("当前没有进行中的决斗")
    duels = data["groups"][group_id]["duels"]
    duel_id = None
    for did, duel in duels.items():
        if duel["player2"] == user_id and duel.get("waiting_accept", False):
            duel_id = did
            break
    if not duel_id:
        await reject_duel_matcher.finish("您没有待接受的决斗")
    del duels[duel_id]
    save_data(data)
    await reject_duel_matcher.finish(MessageSegment.at(user_id) + " 拒绝了决斗")

use_tool_cmd = Alconna("使用道具", ["tool_name:str"])
use_tool_matcher = on_alconna(use_tool_cmd)

@use_tool_matcher.handle()
async def handle_use_tool(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    tool_name = alc_result.query("tool_name")
    data = load_data()
    if group_id not in data["groups"]:
        await use_tool_matcher.finish("当前没有进行中的决斗")
    duels = data["groups"][group_id]["duels"]
    duel_id = None
    for did, duel in duels.items():
        if (duel["player1"] == user_id or duel["player2"] == user_id) and not duel.get("waiting_accept", False):
            duel_id = did
            break
    if not duel_id:
        await use_tool_matcher.finish("您当前不在决斗中")
    duel = duels[duel_id]
    if duel["current_player"] != user_id:
        await use_tool_matcher.finish("当前不是您的回合")
    user_data = data["groups"][group_id]["users"][user_id]
    used_items = duel["used_items1"] if user_id == duel["player1"] else duel["used_items2"]
    if tool_name not in TOOLS:
        await use_tool_matcher.finish("无效的道具名称")
    if tool_name in used_items:
        await use_tool_matcher.finish("您已经使用过该道具，无法再使用！")
    if user_data["items"]["tools"].get(tool_name, 0) <= 0:
        await use_tool_matcher.finish("您尚未拥有该道具")
    user_data["items"]["tools"][tool_name] -= 1
    used_items.append(tool_name)
    duel["pending_tool"] = tool_name
    effect_desc = {
        "手铐": "使对方停止行动一个回合",
        "酒": "下一回合伤害+1",
        "饮料": "回复一点生命值",
        "刀": "直接对对手造成2点伤害"
    }[tool_name]
    save_data(data)
    await use_tool_matcher.finish(f"使用道具成功：{effect_desc}")

shoot_cmd = Alconna("开枪", Args["target", At])
shoot_matcher = on_alconna(shoot_cmd)

@shoot_matcher.handle()
async def handle_shoot(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    # 修改为使用result.args获取参数
    target = alc_result.result.args.get("target") if alc_result.result and alc_result.result.args.get("target") else None
    target_id = str(target.target) if target and hasattr(target, 'target') else None
    data = load_data()
    if group_id not in data["groups"]:
        await shoot_matcher.finish("当前没有进行中的决斗")
    duels = data["groups"][group_id]["duels"]
    duel_id = None
    for did, duel in duels.items():
        if (duel["player1"] == user_id or duel["player2"] == user_id) and not duel.get("waiting_accept", False):
            duel_id = did
            break
    if not duel_id:
        await shoot_matcher.finish("您当前不在决斗中")
    duel = duels[duel_id]
    if duel["current_player"] != user_id:
        await shoot_matcher.finish("当前不是您的回合")
    if target_id not in [duel["player1"], duel["player2"]]:
        await shoot_matcher.finish("无效的目标，请@决斗中的玩家")
    opponent_id = duel["player2"] if user_id == duel["player1"] else duel["player1"]
    damage = 0
    if duel.get("pending_tool") == "手铐" and target_id == opponent_id:
        duel["current_player"] = user_id  # 对手跳过回合，轮到自己
        await shoot_matcher.finish("对手被手铐限制，本回合无法行动！")
    else:
        hit = random.randint(1, 6) == 1
        damage = 1 if hit else 0
        if hit and duel.get("pending_tool") == "酒" and user_id == duel["current_player"]:
            damage += 1
        if duel.get("pending_tool") == "刀" and user_id == duel["current_player"]:
            damage += 2
        if duel.get("pending_tool") == "饮料" and user_id == duel["current_player"] and target_id == user_id:
            if user_id == duel["player1"]:
                duel["health1"] = min(duel["health1"] + 1, 6)
            else:
                duel["health2"] = min(duel["health2"] + 1, 6)
        if hit or duel.get("pending_tool") == "刀":
            if target_id == duel["player1"]:
                duel["health1"] -= damage
            else:
                duel["health2"] -= damage
        duel["pending_tool"] = None
    next_player = opponent_id
    duel["current_player"] = next_player
    duel["turn"] += 1
    health1 = duel["health1"]
    health2 = duel["health2"]
    if health1 <= 0 or health2 <= 0:
        winner_id = duel["player2"] if health1 <= 0 else duel["player1"]
        loser_id = duel["player1"] if health1 <= 0 else duel["player2"]
        winner_data = data["groups"][group_id]["users"][winner_id]
        loser_data = data["groups"][group_id]["users"][loser_id]
        if loser_data["girlfriends"]:
            gf = random.choice(loser_data["girlfriends"])
            loser_data["girlfriends"].remove(gf)
            winner_data["girlfriends"].append(gf)
        winner_data["gold"] += 200
        winner_data["prestige"] += 300
        loser_data["gold"] = max(loser_data["gold"] - 100, 0)
        loser_data["prestige"] = max(loser_data["prestige"] - 100, 0)
        loser_data["title"] = get_user_title(loser_data["prestige"])["name"]
        winner_data["title"] = get_user_title(winner_data["prestige"])["name"]
        del duels[duel_id]
        save_data(data)
        gf_name = gf["name"] if loser_data["girlfriends"] else "无"
        await shoot_matcher.finish(
            MessageSegment.at(winner_id) + f" 获得了本次决斗的胜利，获得200金币和300声望，且抢夺了" +
            MessageSegment.at(loser_id) + f" 的一位“{gf_name}”女友\n" +
            MessageSegment.at(loser_id) + " 失去了100金币，100声望和一位女友"
        )
    else:
        used_items1 = duel["used_items1"]
        used_items2 = duel["used_items2"]
        try:
            msg = MessageSegment.at(user_id) + " 开了一次枪，"
            if damage > 0:
                msg += MessageSegment.at(target_id) + f" 造成了{damage}点伤害"
            else:
                msg += "但很遗憾枪里没有子弹，尚未造成任何伤害"
            msg += "\n" + MessageSegment.at(user_id) + " 的回合结束，请" + MessageSegment.at(next_player) + " 发送相关决斗指令"
            
            # 合并两条消息为一条发送
            msg += "\n当前回合结束\n" + MessageSegment.at(duel['player1']) + f" 剩余血量为：{health1}，已使用道具为：{used_items1 or '无'}\n"
            msg += MessageSegment.at(duel['player2']) + f" 剩余血量为：{health2}，已使用道具为：{used_items2 or '无'}\n新的回合开始！"
            
            save_data(data)
            await shoot_matcher.finish(msg)
        except Exception as e:
            logger.error(f"开枪指令处理失败: {e}")
            return

reset_duel_cmd = Alconna("重置决斗")
reset_duel_matcher = on_alconna(reset_duel_cmd)

@reset_duel_matcher.handle()
async def handle_reset_duel(event: GroupMessageEvent):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    data = load_data()
    if group_id not in data["groups"]:
        await reset_duel_matcher.finish("当前没有进行中的决斗")
    duels = data["groups"][group_id]["duels"]
    duel_id = None
    for did, duel in duels.items():
        if duel["player1"] == user_id or duel["player2"] == user_id:
            duel_id = did
            break
    if not duel_id:
        await reset_duel_matcher.finish("您当前不在决斗中")
    del duels[duel_id]
    save_data(data)
    await reset_duel_matcher.finish("决斗已重置")

# 定时检查决斗超时
@scheduler.scheduled_job("interval", seconds=10)
async def check_duel_timeout():
    data = load_data()
    current_time = int(datetime.now().timestamp())
    for group_id, group in list(data["groups"].items()):
        for duel_id, duel in list(group["duels"].items()):
            if duel.get("waiting_accept", False) and current_time - duel["last_action_time"] > 30:
                del group["duels"][duel_id]
                save_data(data)
                # 通知群组决斗超时
                bot = get_driver().bot
                await bot.send_group_msg(group_id=int(group_id), message="决斗因无人接受已超时取消")
                
# 管理员充值金币
recharge_cmd = Alconna("充值金币", Args["target", At]["amount", int])
recharge_matcher = on_alconna(recharge_cmd, permission=GROUP_ADMIN | GROUP_OWNER)

@recharge_matcher.handle()
async def handle_recharge(event: GroupMessageEvent, alc_result: AlcResult):
    group_id = str(event.group_id)
    user_id = str(event.user_id)
    target = alc_result.result.args.get("target") if alc_result.result and alc_result.result.args.get("target") else None
    target_id = str(target.target) if target and hasattr(target, 'target') else None
    amount = alc_result.result.args.get("amount") if alc_result.result and alc_result.result.args.get("amount") else None
    
    if not target_id or not amount:
        await recharge_matcher.finish("请指定目标用户和充值金额")
    
    data = load_data()
    if group_id not in data["groups"] or target_id not in data["groups"][group_id]["users"]:
        await recharge_matcher.finish("目标用户未在本群创建贵族")
    
    data["groups"][group_id]["users"][target_id]["gold"] += amount
    save_data(data)
    await recharge_matcher.finish(
        MessageSegment.at(user_id) + f" 成功为 " + 
        MessageSegment.at(target_id) + f" 充值 {amount} 金币"
    )


help_cmd = Alconna("帮助")
help_matcher = on_alconna(help_cmd)

@help_matcher.handle()
async def handle_help():
    commands = [
        "创建贵族：创建贵族身份",
        "贵族查询：查询当前爵位、金币、声望和女友数量",
        "贵族签到：每日签到，获得400-600随机金币和声望",
        "贵族约会：消耗300金币招募一个女友",
        "升级爵位：根据声望升级爵位",
        "查询金币：查看当前金币数量",
        "查询女友数量：查看当前女友数量",
        "查询女友 <序号>：查看指定女友的名字和好感度",
        "好感度查询：列出所有女友的好感度",
        "礼物 <礼物名> <女友序号>：赠送礼物提升女友好感度",
        "分手 <女友序号>：分手并扣除200金币",
        "购买道具 <道具名>：购买礼物或决斗道具",
        "道具查询：查看当前持有的道具",
        "贵族决斗 @对手：发起决斗",
        "接受决斗：接受待处理的决斗",
        "拒绝决斗：拒绝待处理的决斗",
        "使用道具 <道具名>：在决斗中使用道具",
        "开枪 @目标：在决斗中开枪",
        "重置决斗：结束当前决斗"
    ]
    await help_matcher.finish("可用指令：\n" + "\n".join(commands))