import asyncio
import sqlite3
import random
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment, GroupMessageEvent
from nonebot.plugin import PluginMetadata, require
require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
from nonebot_plugin_alconna import Alconna, on_alconna, Args, At
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_localstore import get_data_dir
from .config import GIFTS, ITEMS, TITLES, OPERATOR_RARITY, DUEL_WAIT_TIME, BET_WAIT_TIME

# 插件元数据
__version__ = "0.3.16"
__plugin_meta__ = PluginMetadata(
    name="贵族决斗",
    description="一个贵族决斗小游戏",
    usage="发送'贵族帮助'查看所有指令",
    type="application",
    homepage="https://github.com/cikasaaa/nonebot-plugin-NobleDuel",
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "cikasaaa",
        "version": __version__,
        "dependencies": {
            "nonebot2": ">=2.3.0",
            "nonebot_plugin_apscheduler": ">=0.5.0",
            "nonebot_plugin_alconna": "0.55.0",
            "nonebot_plugin_localstore": ">=0.7.0"
        }
    }
)

# 数据库路径
DB_PATH = get_data_dir("nonebot_plugin_NobleDuel") / "data.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
#控制台显示数据存路径
print(DB_PATH)
# 全局变量
current_duel = None
bet_players = {}
duel_timeout_task = None
bet_timeout_task = None


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.init_db()
    def init_db(self):
        cursor = self.conn.cursor()
        # 用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                coins INTEGER DEFAULT 1000,
                reputation INTEGER DEFAULT 500,
                title TEXT DEFAULT '男爵',
                last_checkin DATE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                max_streak INTEGER DEFAULT 0
            )
        """)
        # 干员表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS girlfriends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                girlfriend_id INTEGER,
                girlfriend_name TEXT,
                affection INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        # 礼物表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                gift_name TEXT,
                quantity INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        self.conn.commit()
    
    def create_noble(self, user_id: str) -> bool:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            conn.close()
            return False
        cursor.execute("""
            INSERT INTO users (user_id, coins, reputation, title) 
            VALUES (?, 1000, 500, '男爵')
        """, (user_id,))
        conn.commit()
        conn.close()
        return True
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "user_id": row[0],
                "coins": row[1],
                "reputation": row[2],
                "title": row[3],
                "last_checkin": row[4],
                "created_at": row[5]
            }
        return None
    
    def update_user(self, user_id: str, **kwargs):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            # 开始事务
            conn.execute("BEGIN TRANSACTION")
            fields = []
            values = []
            for key, value in kwargs.items():
                fields.append(f"{key} = ?")
                values.append(value)
            values.append(user_id)
            cursor.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", values)
            # 提交事务
            conn.commit()
        except Exception as e:
            # 如果发生错误，回滚事务
            if conn:
                conn.rollback()
            print(f"Error updating user {user_id}: {e}")
            raise e
        finally:
            # 确保连接被关闭
            if conn:
                conn.close()
    
    def add_girlfriend(self, user_id: str, girlfriend_id: int, girlfriend_name: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO girlfriends (user_id, girlfriend_id, girlfriend_name, affection)
            VALUES (?, ?, ?, 0)
        """, (user_id, girlfriend_id, girlfriend_name))
        conn.commit()
        conn.close()
    
    def get_girlfriends(self, user_id: str) -> List[Dict]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT girlfriend_id, girlfriend_name, affection 
            FROM girlfriends WHERE user_id = ?
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{"id": row[0], "name": row[1], "affection": row[2]} for row in rows]
    
    def remove_girlfriend(self, user_id: str, girlfriend_name: str) -> bool:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM girlfriends 
            WHERE user_id = ? AND girlfriend_name = ?
        """, (user_id, girlfriend_name))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def update_affection(self, user_id: str, girlfriend_name: str, affection_change: int):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE girlfriends 
            SET affection = affection + ?
            WHERE user_id = ? AND girlfriend_name = ?
        """, (affection_change, user_id, girlfriend_name))
        conn.commit()
        conn.close()
    
    def get_gift_quantity(self, user_id: str, gift_name: str) -> int:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT quantity FROM gifts 
            WHERE user_id = ? AND gift_name = ?
        """, (user_id, gift_name))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    
    def update_gift_quantity(self, user_id: str, gift_name: str, quantity_change: int) -> bool:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            # 获取当前数量
            cursor.execute("""
                SELECT quantity FROM gifts 
                WHERE user_id = ? AND gift_name = ?
            """, (user_id, gift_name))
            row = cursor.fetchone()
            current_quantity = row[0] if row else 0
            # 检查是否会导致数量为负数
            if current_quantity + quantity_change < 0:
                conn.close()
                return False
            new_quantity = current_quantity + quantity_change
            if new_quantity > 0:
                # 如果新数量大于0，更新记录
                cursor.execute("""
                    INSERT OR REPLACE INTO gifts (user_id, gift_name, quantity)
                    VALUES (?, ?, ?)
                """, (user_id, gift_name, new_quantity))
            else:
                # 如果新数量为0，删除记录
                cursor.execute("""
                    DELETE FROM gifts 
                    WHERE user_id = ? AND gift_name = ?
                """, (user_id, gift_name))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating gift quantity: {e}")
            if conn:
                conn.close()
            return False
    
    def get_all_gifts(self, user_id: str) -> List[Dict]:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT gift_name, quantity FROM gifts 
            WHERE user_id = ? AND quantity > 0
            ORDER BY gift_name
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{"name": row[0], "quantity": row[1]} for row in rows]

db = Database()

class DuelGame:
    def __init__(self, challenger_id: str, target_id: str, group_id: str):
        self.challenger_id = challenger_id
        self.target_id = target_id
        self.group_id = group_id
        self.challenger_health = 6
        self.target_health = 6
        self.current_player = challenger_id
        self.round = 1
        self.real_bullets = 0
        self.blank_bullets = 0
        self.bullets = []
        self.bullet_index = 0
        self.challenger_items = []
        self.target_items = []
        self.can_shoot = True
        self.handcuff_skip = False
        self.handcuffed_player = None  # 添加被禁锢玩家属性
        self.accepted = False
        self.started = False
        self.saw_used = False  # 添加手锯使用状态
    
    def check_death(self) -> bool:
        """检查是否有人死亡"""
        return self.challenger_health <= 0 or self.target_health <= 0
    def check_next_round(self) -> bool:
        """检查是否需要进入下一轮"""
        return self.bullet_index >= len(self.bullets)
    def next_round(self):
        """进入下一轮"""
        self.round += 1
        self.generate_bullets()  # 直接调用方法，不使用返回值
        # 保存旧道具
        old_challenger_items = self.challenger_items.copy()
        old_target_items = self.target_items.copy()
        # 重置道具
        self.challenger_items = []
        self.target_items = []
        self.draw_items()
        # 合并道具并处理超出限制的情况
        self.challenger_items = old_challenger_items + self.challenger_items
        self.target_items = old_target_items + self.target_items
        # 如果道具超过6个，移除最早的道具
        if len(self.challenger_items) > 6:
            discarded_items = self.challenger_items[:-6]
            self.challenger_items = self.challenger_items[-6:]
            self.discarded_challenger_items = discarded_items
        else:
            self.discarded_challenger_items = []
        if len(self.target_items) > 6:
            discarded_items = self.target_items[:-6]
            self.target_items = self.target_items[-6:]
            self.discarded_target_items = discarded_items
        else:
            self.discarded_target_items = []
        # 重置手锯状态
        self.saw_used = False
        # 重置手铐状态
        self.handcuff_skip = False
        self.handcuffed_player = None
    
    def shoot(self, target_id: str) -> str:
        """开枪"""
        if not self.can_shoot:
            return "cannot_shoot"
        if self.bullet_index >= len(self.bullets):
            return "no_bullets"
        hit = self.bullets[self.bullet_index]
        self.bullet_index += 1
        if hit:
            # 只有在当前玩家使用手锯且是实弹时才增加伤害
            damage = 2 if self.saw_used and self.current_player == target_id else 1
            if target_id == self.challenger_id:
                self.challenger_health -= damage
            else:
                self.target_health -= damage
            self.saw_used = False  # 使用后重置手锯状态
            # 切换回合
            self.current_player = self.target_id if self.current_player == self.challenger_id else self.challenger_id
        else:
            # 如果是空弹，重置手锯状态
            self.saw_used = False
            # 如果是空弹且目标是自己，则不切换回合
            if target_id != self.current_player:
                self.current_player = self.target_id if self.current_player == self.challenger_id else self.challenger_id
        
        # 检查是否需要进入下一局
        if self.bullet_index >= len(self.bullets):
            return "next_round"
        return "hit" if hit else "miss"
    
    def draw_items(self):
        """抽取道具"""
        # 从ITEMS字典中获取所有道具名称
        items = list(ITEMS.keys())
        # 根据概率权重抽取道具
        weights = [ITEMS[item]["probability"] for item in items]
        # 根据回合数决定抽取道具数量
        if self.round == 1:
            item_count = 2
        elif self.round == 2:
            item_count = 3
        else:  # 第三局
            item_count = 4
        # 每个玩家抽取道具
        self.challenger_items = random.choices(items, weights=weights, k=item_count)
        self.target_items = random.choices(items, weights=weights, k=item_count)
    
    def generate_bullets(self):
        """生成子弹序列"""
        if self.round == 1:
            # 第一局子弹填充逻辑
            prob = random.randint(1, 100)
            if prob <= 55:  # 55%概率：4空弹2实弹
                self.blank_bullets = 4
                self.real_bullets = 2
            elif prob <= 75:  # 20%概率：3空弹3实弹
                self.blank_bullets = 3
                self.real_bullets = 3
            elif prob <= 90:  # 15%概率：2空弹4实弹
                self.blank_bullets = 2
                self.real_bullets = 4
            else:  # 10%概率：1空弹5实弹
                self.blank_bullets = 1
                self.real_bullets = 5
        else:
            # 第二局及以后的子弹填充逻辑
            prob = random.randint(1, 100)
            if prob <= 60:  # 60%概率：3空弹3实弹
                self.blank_bullets = 3
                self.real_bullets = 3
            elif prob <= 90:  # 30%概率：2空弹4实弹
                self.blank_bullets = 2
                self.real_bullets = 4
            else:  # 10%概率：1空弹5实弹
                self.blank_bullets = 1
                self.real_bullets = 5
        # 生成子弹序列
        self.bullets = [True] * self.real_bullets + [False] * self.blank_bullets
        random.shuffle(self.bullets)
        self.bullet_index = 0
        # 验证子弹数量
        actual_real = sum(1 for bullet in self.bullets if bullet)
        actual_blank = sum(1 for bullet in self.bullets if not bullet)
        # 如果数量不一致，重新生成
        if actual_real != self.real_bullets or actual_blank != self.blank_bullets:
            self.bullets = [True] * self.real_bullets + [False] * self.blank_bullets
            random.shuffle(self.bullets)
            self.bullet_index = 0
    
    def use_item(self, user_id: str, item_name: str, target_item: str | None = None) -> str:
        # 检查是否被手铐禁锢
        if self.handcuff_skip and self.current_player == self.handcuffed_player:
            self.handcuff_skip = False
            self.handcuffed_player = None
            return "您当前被手铐禁锢，无法使用道具！"
        items = self.challenger_items if user_id == self.challenger_id else self.target_items
        if item_name not in items:
            return "您没有这个道具！"
        items.remove(item_name)
        if item_name == "放大镜":
            if self.bullet_index < len(self.bullets):
                bullet_type = "实弹" if self.bullets[self.bullet_index] else "空弹"
                return f"使用道具成功，下一发子弹是{bullet_type}"
            return "使用道具成功，但弹仓已空"
        elif item_name == "香烟":
            if user_id == self.challenger_id:
                self.challenger_health = min(6, self.challenger_health + 1)
            else:
                self.target_health = min(6, self.target_health + 1)
            return "使用道具成功，回复了1点生命值"
        elif item_name == "手铐":
            # 设置手铐状态，并记录被禁锢的玩家（对手）
            self.handcuff_skip = True
            # 设置被禁锢的玩家为对手
            self.handcuffed_player = self.target_id if user_id == self.challenger_id else self.challenger_id
            return "使用道具成功，对手将跳过下一回合"
        elif item_name == "啤酒":
            if self.bullet_index < len(self.bullets):
                bullet_type = "实弹" if self.bullets[self.bullet_index] else "空弹"
                self.bullets.pop(self.bullet_index)
                return f"使用道具成功，退掉了一发{bullet_type}"
            return "使用道具成功，但弹仓已空"
        elif item_name == "手锯":
            self.saw_used = True
            return "使用道具成功，下一发实弹伤害+1"
        elif item_name == "逆转器":
            if self.bullet_index < len(self.bullets):
                self.bullets[self.bullet_index] = not self.bullets[self.bullet_index]
                return "使用道具成功，当前子弹类型已转换"
            return "使用道具成功，但弹仓已空"
        elif item_name == "过期药":
            if random.random() < 0.5:
                if user_id == self.challenger_id:
                    self.challenger_health = min(6, self.challenger_health + 2)
                else:
                    self.target_health = min(6, self.target_health + 2)
                return "使用道具成功，回复了2点生命值"
            else:
                if user_id == self.challenger_id:
                    self.challenger_health = max(0, self.challenger_health - 1)
                else:
                    self.target_health = max(0, self.target_health - 1)
                return "使用道具成功，但扣除了1点生命值"
        elif item_name == "肾上腺素":
            opponent_items = self.target_items if user_id == self.challenger_id else self.challenger_items
            available_items = [item for item in opponent_items if item != "肾上腺素"]
            if not available_items:
                return "使用道具成功，但对手没有可偷取的道具"
            if target_item and target_item in available_items:
                stolen_item = target_item
            else:
                stolen_item = random.choice(available_items)
            opponent_items.remove(stolen_item)
            # 将偷取的道具添加到自己的道具列表中
            if user_id == self.challenger_id:
                self.challenger_items.append(stolen_item)
            else:
                self.target_items.append(stolen_item)
            return f"使用道具成功，偷取了对手的{stolen_item}并使用：" + self.use_item(user_id, stolen_item)
        elif item_name == "一次性手机":
            if self.bullets:
                random_index = random.randint(0, len(self.bullets) - 1)
                bullet_type = "实弹" if self.bullets[random_index] else "空弹"
                return f"使用道具成功，第{random_index + 1}发子弹是{bullet_type}"
            return "使用道具成功，但弹仓已空"
        return "使用道具成功"


# 指令定义
create_noble_cmd = Alconna("创建贵族")
create_noble_matcher = on_alconna(create_noble_cmd)
recharge_coins_cmd = Alconna("充值金币", Args["target", At], Args["amount", int])
recharge_coins_matcher = on_alconna(recharge_coins_cmd)
query_noble_cmd = Alconna("贵族查询")
query_noble_matcher = on_alconna(query_noble_cmd)
recruit_cmd = Alconna("招募干员") 
recruit_matcher = on_alconna(recruit_cmd)
upgrade_title_cmd = Alconna("升级爵位")
upgrade_title_matcher = on_alconna(upgrade_title_cmd)
checkin_cmd = Alconna("贵族签到")
checkin_matcher = on_alconna(checkin_cmd)
duel_cmd = Alconna("贵族决斗", Args["target", At])
duel_matcher = on_alconna(duel_cmd)
accept_duel_cmd = Alconna("接受决斗")
accept_duel_matcher = on_alconna(accept_duel_cmd)
refuse_duel_cmd = Alconna("拒绝决斗")
refuse_duel_matcher = on_alconna(refuse_duel_cmd)
bet_cmd = Alconna("下注", Args["target", At])
bet_matcher = on_alconna(bet_cmd)
shoot_cmd = Alconna("开枪", Args["target", At])
shoot_matcher = on_alconna(shoot_cmd)
use_item_cmd = Alconna("使用道具", Args["item_name", str])
use_item_matcher = on_alconna(use_item_cmd)
query_affection_cmd = Alconna("好感度查询")
query_affection_matcher = on_alconna(query_affection_cmd)
query_partner_cmd = Alconna("干员查询") 
query_partner_matcher = on_alconna(query_partner_cmd)
specific_affection_cmd = Alconna("好感度查询", Args["partner_name", str]) 
specific_affection_matcher = on_alconna(specific_affection_cmd)
gift_cmd = Alconna("礼物", Args["gift_name", str], Args["partner_name", str])
gift_matcher = on_alconna(gift_cmd)
dismiss_cmd = Alconna("解雇", Args["partner_name", str]) 
dismiss_matcher = on_alconna(dismiss_cmd)
buy_gift_cmd = Alconna("购买礼物", Args["gift_name", str])
buy_gift_matcher = on_alconna(buy_gift_cmd)
query_gifts_cmd = Alconna("礼物查询")
query_gifts_matcher = on_alconna(query_gifts_cmd)
item_intro_cmd = Alconna("道具介绍") 
item_intro_matcher = on_alconna(item_intro_cmd)
query_items_cmd = Alconna("道具查询") 
query_items_matcher = on_alconna(query_items_cmd)
help_cmd = Alconna("贵族帮助")
help_matcher = on_alconna(help_cmd)
reset_duel_cmd = Alconna("重置决斗")
reset_duel_matcher = on_alconna(reset_duel_cmd)
noble_rank_cmd = Alconna("贵族排行")
noble_rank_matcher = on_alconna(noble_rank_cmd)

@noble_rank_matcher.handle()
async def handle_noble_rank(event: GroupMessageEvent):
    # 获取群成员列表
    from nonebot import get_bot
    bot = get_bot()
    try:
        member_list = await bot.get_group_member_list(group_id=event.group_id)
    except:
        await noble_rank_matcher.send("获取群成员信息失败！")
        return
    # 获取所有贵族信息
    nobles = []
    for member in member_list:
        user_id = str(member["user_id"])
        user = db.get_user(user_id)
        if user:
            # 获取干员数量
            girlfriends = db.get_girlfriends(user_id)
            gf_count = len(girlfriends)
            
            nobles.append({
                "user_id": user_id,
                "nickname": member.get("card") or member.get("nickname") or str(user_id),
                "coins": user["coins"],
                "reputation": user["reputation"],
                "gf_count": gf_count
            })
    
    if not nobles:
        await noble_rank_matcher.send("当前群内还没有贵族！")
        return
    # 构建消息
    message = "【贵族排行榜】\n"
    message += "━━━━━━━━━━\n"
    # 按金币排序
    coins_rank = sorted(nobles, key=lambda x: x["coins"], reverse=True)[:10]
    for i, noble in enumerate(coins_rank, 1):
        # 获取用户信息
        user = db.get_user(noble['user_id'])
        if not user:
            continue
        # 计算胜率
        total_games = user.get("wins", 0) + user.get("losses", 0)
        win_rate = "0%" if total_games == 0 else f"{(user.get('wins', 0) / total_games * 100):.1f}%"
        # 格式化数字
        coins = f"{noble['coins']:,}"
        reputation = f"{noble['reputation']:,}"
        # 构建个人展示信息
        message += f"{i}、{noble['nickname']}\n"
        message += f"爵位：{user['title']}\n"
        message += f"金币数：{coins}\n"
        message += f"声望数：{reputation}\n"
        message += f"干员数：{noble['gf_count']}\n"
        message += f"胜率：{win_rate}\n"
        message += f"最高连胜：{user.get('max_streak', 0)}\n"
        message += "━━━━━━━━━━\n"
    await noble_rank_matcher.send(message)



# 工具函数
def get_user_title(reputation: int) -> str:
    for title in reversed(TITLES):
        if reputation >= title["reputation"]:
            return title["name"]
    return "男爵"

def get_max_operators(title: str) -> int:
    for t in TITLES:
        if t["name"] == title:
            return t["max_operators"]
    return 5

def extract_user_id(at_segment) -> str:
    """从At消息段中提取用户ID"""
    if isinstance(at_segment, At):
        return str(at_segment.target)
    elif hasattr(at_segment, 'data') and 'qq' in at_segment.data:
        return str(at_segment.data['qq'])
    return str(at_segment)

# 定时任务：每日重置签到状态
@scheduler.scheduled_job("cron", hour=0, minute=0)
async def reset_daily_checkin():
    # 这里可以重置用户的签到状态，但由于我们使用日期检查，所以不需要额外操作
    pass

# 处理函数
@create_noble_matcher.handle()
async def handle_create_noble(event: GroupMessageEvent):
    user_id = str(event.user_id)
    
    if db.create_noble(user_id):
        await create_noble_matcher.send("贵族创建成功！您现在是一名男爵，祝您好运！")
    else:
        await create_noble_matcher.send("您已经是贵族啦！不能重复创建！")

@query_noble_matcher.handle()
async def handle_query_noble(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await query_noble_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    
    girlfriends = db.get_girlfriends(user_id)
    girlfriend_count = len(girlfriends)
    message = f"您当前的爵位是：{user['title']}\n"
    message += f"您当前拥有{user['reputation']}声望\n"
    message += f"您当前持有{user['coins']}金币\n"
    message += f"您当前拥有{girlfriend_count}个干员"
    await query_noble_matcher.send(message)

@recruit_matcher.handle()
async def handle_recruit(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await recruit_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    if user["coins"] < 300:
        await recruit_matcher.send("您目前的金币数量不足，可以通过每日签到和贵族决斗来获取金币")
        return
    operators = db.get_girlfriends(user_id)
    max_operators = get_max_operators(user["title"])
    if len(operators) >= max_operators:
        await recruit_matcher.send(f"您已达到当前爵位的干员上限({max_operators}个)")
        return
    # 获取所有已招募的干员名称
    owned_names = {gf["name"] for gf in operators}
    # 从干员池中随机选择一个未被招募的干员
    available_operators = [name for name in OPERATOR_RARITY.keys() if name not in owned_names]
    if not available_operators:
        await recruit_matcher.send("所有干员都已被招募！")
        return
    operator_name = random.choice(available_operators)
    operator_id = list(OPERATOR_RARITY.keys()).index(operator_name) + 1
    operator_rarity = OPERATOR_RARITY.get(operator_name, 3)
    # 扣除金币并添加干员
    db.update_user(user_id, coins=user["coins"] - 300)
    db.add_girlfriend(user_id, operator_id, operator_name)
    await recruit_matcher.send(f"花费300金币招募干员成功，恭喜你招募到了{operator_rarity}星干员：{operator_name}")


@query_partner_matcher.handle()  # 修改函数名
async def handle_query_partner(event: GroupMessageEvent):  # 修改函数名
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await query_partner_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    operators = db.get_girlfriends(user_id)  # 保持数据库函数名不变
    if not operators:
        await query_partner_matcher.send("您还没有干员！")
        return
    operator_names = [f"{OPERATOR_RARITY.get(gf['name'], 3)}★ {gf['name']}" for gf in operators]
    message = f"您目前拥有以下干员：\n{', '.join(operator_names)}"
    await query_partner_matcher.send(message)



@upgrade_title_matcher.handle()
async def handle_upgrade_title(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await upgrade_title_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    current_title = user["title"]
    current_reputation = user["reputation"]
    # 找到下一个爵位
    next_title = None
    for i, title in enumerate(TITLES):
        if title["name"] == current_title and i < len(TITLES) - 1:
            next_title = TITLES[i + 1]
            break
    if not next_title:
        await upgrade_title_matcher.send("您已经是最高爵位了！")
        return
    if current_reputation >= next_title["reputation"]:
        # 扣除升级所需的声望
        new_reputation = current_reputation - next_title["reputation"]
        db.update_user(user_id, title=next_title["name"], reputation=new_reputation)
        await upgrade_title_matcher.send(f"升级爵位成功，消耗了{next_title['reputation']}声望，您目前的爵位是{next_title['name']}，剩余声望{new_reputation}")
    else:
        needed = next_title["reputation"] - current_reputation
        await upgrade_title_matcher.send(f"很抱歉，您的声望目前还不够升级到下一个爵位，还需要{needed}声望，请努力加油获取声望吧")




@checkin_matcher.handle()
async def handle_checkin(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await checkin_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    today = datetime.now().date()
    last_checkin = user["last_checkin"]
    if last_checkin and str(today) == last_checkin:
        await checkin_matcher.send("您今天已经签到过了！")
        return
    coins_reward = random.randint(300, 400)
    reputation_reward = random.randint(150, 250)
    new_coins = user["coins"] + coins_reward
    new_reputation = user["reputation"] + reputation_reward
    db.update_user(user_id, 
                   coins=new_coins, 
                   reputation=new_reputation, 
                   last_checkin=str(today))
    
    await checkin_matcher.send(f"签到成功，今日奖励{coins_reward}金币和{reputation_reward}声望")




@duel_matcher.handle()
async def handle_duel(event: GroupMessageEvent, target: At):
    global current_duel, duel_timeout_task
    challenger_id = str(event.user_id)
    target_id = extract_user_id(target)
    group_id = str(event.group_id)
    if current_duel:
        await duel_matcher.send("当前已经存在决斗，请先等待本次决斗结束")
        return
    # 检查双方是否都是贵族且有女友
    challenger = db.get_user(challenger_id)
    target_user = db.get_user(target_id)
    if not challenger:
        await duel_matcher.send("您还未创建贵族！")
        return
    if not target_user:
        await duel_matcher.send("对方还未创建贵族！")
        return
    # 检查发起者是否有足够的金币和声望
    if challenger["coins"] < 100 or challenger["reputation"] < 50:
        await duel_matcher.send("发起决斗需要消耗100金币和50声望！")
        return
    challenger_gfs = db.get_girlfriends(challenger_id)
    target_gfs = db.get_girlfriends(target_id)
    if not challenger_gfs:
        await duel_matcher.send("您还没有干员，无法进行决斗！")
        return
    if not target_gfs:
        await duel_matcher.send("对方还没有干员，无法进行决斗！")
        return
    
    # 扣除发起者的金币和声望
    db.update_user(challenger_id, 
                  coins=challenger["coins"] - 100,
                  reputation=challenger["reputation"] - 50)
    current_duel = DuelGame(challenger_id, target_id, group_id)
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    target_name = await get_member_info(bot, event.group_id, int(target_id))
    await duel_matcher.send(f"决斗已发起\n请@{target_name}在{DUEL_WAIT_TIME}秒内发送指令接受决斗或拒绝决斗，超时则本次决斗作废")
    # 设置超时
    duel_timeout_task = asyncio.create_task(duel_timeout())
async def duel_timeout():
    global current_duel
    await asyncio.sleep(DUEL_WAIT_TIME)
    if current_duel and not current_duel.accepted:
        current_duel = None


@accept_duel_matcher.handle()
async def handle_accept_duel(event: GroupMessageEvent):
    global current_duel, bet_timeout_task, bet_players
    user_id = str(event.user_id)
    if not current_duel:
        await accept_duel_matcher.send("当前没有进行中的决斗！")
        return
    if user_id != current_duel.target_id:
        await accept_duel_matcher.send("您不是被挑战者！")
        return
    if current_duel.accepted:
        await accept_duel_matcher.send("决斗已经被接受！")
        return
    current_duel.accepted = True
    bet_players = {}
    
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    user_name = await get_member_info(bot, event.group_id, int(user_id))
    await accept_duel_matcher.send(f"@{user_name}接受决斗成功\n现在有{BET_WAIT_TIME}秒的时间进行下注,请发送指令'下注+@下注对象'进行下注")
    # 设置下注时间
    bet_timeout_task = asyncio.create_task(start_duel())

async def start_duel():
    global current_duel, bet_players
    await asyncio.sleep(BET_WAIT_TIME)
    if not current_duel:
        return
    current_duel.started = True
    
    # 开始第一局
    current_duel.generate_bullets()
    current_duel.draw_items()
    challenger_items_str = " ".join(current_duel.challenger_items)
    target_items_str = " ".join(current_duel.target_items)
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    challenger_name = await get_member_info(bot, int(current_duel.group_id), int(current_duel.challenger_id))
    target_name = await get_member_info(bot, int(current_duel.group_id), int(current_duel.target_id))
    message = f"决斗正式开始，如果决斗出现bug请发送'重置决斗'来终止决斗\n"
    message += f"第一局开始，目前有{current_duel.real_bullets}个实弹，{current_duel.blank_bullets}个空弹\n"
    message += f"@{challenger_name} 抽取到了道具 {challenger_items_str}\n"
    message += f"@{target_name} 抽取到了道具 {target_items_str}\n"
    message += f"请 @{challenger_name} 发送决斗指令"
    # 发送消息到群
    await bot.send_group_msg(group_id=int(current_duel.group_id), message=message)


@refuse_duel_matcher.handle()
async def handle_refuse_duel(event: GroupMessageEvent):
    global current_duel
    user_id = str(event.user_id)
    if not current_duel:
        await refuse_duel_matcher.send("当前没有进行中的决斗！")
        return
    if user_id != current_duel.target_id:
        await refuse_duel_matcher.send("您不是被挑战者！")
        return
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    user_name = await get_member_info(bot, event.group_id, int(user_id))
    await refuse_duel_matcher.send(f"@{user_name}拒绝了决斗")
    current_duel = None


@bet_matcher.handle()
async def handle_bet(event: GroupMessageEvent, target: At):
    global current_duel, bet_players
    user_id = str(event.user_id)
    target_id = extract_user_id(target)
    if not current_duel or not current_duel.accepted or current_duel.started:
        await bet_matcher.send("当前没有可下注的决斗！")
        return
    if target_id not in [current_duel.challenger_id, current_duel.target_id]:
        await bet_matcher.send("只能对决斗中的玩家下注！")
        return
    if user_id in bet_players:
        await bet_matcher.send("不能重复下注！")
        return
    user = db.get_user(user_id)
    if not user:
        await bet_matcher.send("您还未创建贵族！")
        return
    if user["coins"] < 200:
        await bet_matcher.send("下注需要200金币！")
        return
    # 扣除下注金币
    db.update_user(user_id, coins=user["coins"] - 200)
    # 记录下注信息
    bet_players[user_id] = target_id
    # 获取目标用户昵称
    from nonebot import get_bot
    bot = get_bot()
    target_name = await get_member_info(bot, event.group_id, int(target_id))
    await bet_matcher.send(f"您已下注@{target_name}，扣除200金币")

async def get_member_info(bot: Any, group_id: int, user_id: int) -> str:
    """获取群成员信息"""
    try:
        member_info = await bot.get_group_member_info(group_id=group_id, user_id=user_id)
        return member_info.get("card") or member_info.get("nickname") or str(user_id)
    except:
        return str(user_id)



@shoot_matcher.handle()
async def handle_shoot(event: GroupMessageEvent, target: At):
    global current_duel
    user_id = str(event.user_id)
    target_id = extract_user_id(target)
    if not current_duel or not current_duel.started:
        await shoot_matcher.send("当前没有进行中的决斗！")
        return
    if user_id != current_duel.current_player:
        await shoot_matcher.send("还没轮到您的回合！")
        return
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    user_name = await get_member_info(bot, event.group_id, int(user_id))
    target_name = await get_member_info(bot, event.group_id, int(target_id))
    if target_id not in [current_duel.challenger_id, current_duel.target_id]:
        await shoot_matcher.send("只能对决斗中的玩家开枪！")
        return
    if not current_duel.can_shoot:
        await shoot_matcher.send("您当前不能开枪！")
        return
    result = current_duel.shoot(target_id)
    
    try:
        if result == "hit":
            if target_id == user_id:
                await shoot_matcher.send(f"@{user_name} 对自己开了一枪，造成了伤害！")
            else:
                await shoot_matcher.send(f"@{user_name} 对 @{target_name} 开了一枪，造成了伤害！")
        elif result == "next_round":
            if target_id == user_id:
                await shoot_matcher.send(f"@{user_name} 对自己开了一枪，是空弹！子弹已用完，进入下一局。")
            else:
                await shoot_matcher.send(f"@{user_name} 对 @{target_name} 开了一枪，是空弹！子弹已用完，进入下一局。")
        else:
            if target_id == user_id:
                await shoot_matcher.send(f"@{user_name} 对自己开了一枪，但由于子弹是空弹所以 @{user_name} 的回合继续")
                # 如果是空弹且目标是自己，不发送回合结束消息
                return
            else:
                await shoot_matcher.send(f"@{user_name} 对 @{target_name} 开了一枪，是空弹！")
    except:
        # 如果发送消息失败，不切换回合
        return
    
    # 检查是否有人死亡
    if current_duel.check_death():
        winner_id = current_duel.challenger_id if current_duel.target_health <= 0 else current_duel.target_id
        loser_id = current_duel.target_id if current_duel.target_health <= 0 else current_duel.challenger_id
        
        winner_name = await get_member_info(bot, event.group_id, int(winner_id))
        loser_name = await get_member_info(bot, event.group_id, int(loser_id))
        
        try:
            # 获取双方的干员列表
            winner_gfs = db.get_girlfriends(winner_id)
            loser_gfs = db.get_girlfriends(loser_id)
            
            # 随机选择一个输家的干员
            stolen_gf_name = "无干员可抢"
            if loser_gfs:
                stolen_gf = random.choice(loser_gfs)
                stolen_gf_name = stolen_gf["name"]
                # 从输家移除干员
                db.remove_girlfriend(loser_id, stolen_gf_name)
                # 添加到赢家
                db.add_girlfriend(winner_id, stolen_gf["id"], stolen_gf_name)
            
            # 更新金币和声望
            winner = db.get_user(winner_id)
            loser = db.get_user(loser_id)
            
            if winner and loser:
                try:
                    # 更新胜率
                    winner_wins = winner.get("wins", 0) + 1
                    loser_losses = loser.get("losses", 0) + 1
                    
                    # 更新连胜
                    winner_current_streak = winner.get("current_streak", 0) + 1
                    winner_max_streak = max(winner.get("max_streak", 0), winner_current_streak)
                    
                    # 重置失败者连胜
                    loser_current_streak = 0
                    
                    # 更新金币和声望
                    db.update_user(winner_id, 
                                 coins=winner["coins"] + 400,
                                 reputation=winner["reputation"] + 200,
                                 wins=winner_wins,
                                 current_streak=winner_current_streak,
                                 max_streak=winner_max_streak)
                    db.update_user(loser_id,
                                 coins=loser["coins"] - 300,
                                 reputation=loser["reputation"] - 100,
                                 losses=loser_losses,
                                 current_streak=loser_current_streak)
                    
                    # 检查连胜奖励
                    streak_rewards = {
                        3: {"coins": 200, "reputation": 100},
                        5: {"coins": 500, "reputation": 200},
                        10: {"coins": 2000, "reputation": 600}
                    }
                    
                    if winner_current_streak in streak_rewards:
                        reward = streak_rewards[winner_current_streak]
                        db.update_user(winner_id,
                                     coins=winner["coins"] + 400 + reward["coins"],
                                     reputation=winner["reputation"] + 200 + reward["reputation"])
                        settlement_message += f"\n【连胜奖励】\n"
                        settlement_message += f"• 达成{winner_current_streak}连胜！\n"
                        settlement_message += f"• 额外奖励：{reward['coins']}金币，{reward['reputation']}声望\n"
                except Exception as e:
                    print(f"Error updating user data: {e}")
                    return
            
            # 构建结算消息
            settlement_message = f"决斗结束！@{winner_name} 获得了胜利！\n"
            settlement_message += f"【失败方】@{loser_name}\n"
            settlement_message += f"• 损失：{stolen_gf_name}（干员）\n"
            settlement_message += f"• 扣除：300金币，100声望\n"
            settlement_message += f"【胜利方】@{winner_name}\n"
            settlement_message += f"• 获得：{stolen_gf_name}（干员）\n"
            settlement_message += f"• 奖励：400金币，200声望\n"
            
            # 处理下注
            if bet_players:
                settlement_message += "【下注结算】\n"
                for bettor_id, bet_target_id in bet_players.items():
                    bettor = db.get_user(bettor_id)
                    if bettor:
                        bettor_name = await get_member_info(bot, event.group_id, int(bettor_id))
                        if bet_target_id == winner_id:
                            # 下注成功，获得奖励
                            db.update_user(bettor_id, 
                                         coins=bettor["coins"] + 300,
                                         reputation=bettor["reputation"] + 50)
                            settlement_message += f"@{bettor_name} 下注成功：+300金币，+50声望\n"
                        else:
                            # 下注失败，扣除金币和声望
                            db.update_user(bettor_id,
                                         coins=bettor["coins"] - 300,
                                         reputation=bettor["reputation"] - 25)
                            settlement_message += f"@{bettor_name} 下注失败：-300金币，-25声望\n"
            
            await shoot_matcher.finish(settlement_message)
        except Exception as e:
            print(f"Error in duel settlement: {e}")
            current_duel = None
            return
    
    # 检查是否需要进入下一局
    if current_duel.check_next_round():
        current_duel.next_round()
        challenger_items_str = " ".join(current_duel.challenger_items)
        target_items_str = " ".join(current_duel.target_items)
        # 获取用户昵称
        from nonebot import get_bot
        bot = get_bot()
        challenger_name = await get_member_info(bot, event.group_id, int(current_duel.challenger_id))
        target_name = await get_member_info(bot, event.group_id, int(current_duel.target_id))
        current_player_name = await get_member_info(bot, event.group_id, int(current_duel.current_player))
        
        message = f"第{current_duel.round}局开始，目前有{current_duel.real_bullets}个实弹，{current_duel.blank_bullets}个空弹\n"
        # 添加道具废弃提示
        if current_duel.discarded_challenger_items:
            message += f"@{challenger_name} 废弃了道具：{', '.join(current_duel.discarded_challenger_items)}\n"
        if current_duel.discarded_target_items:
            message += f"@{target_name} 废弃了道具：{', '.join(current_duel.discarded_target_items)}\n"
        message += f"@{challenger_name} 当前持有道具：{challenger_items_str}\n"
        message += f"@{target_name} 当前持有道具：{target_items_str}\n"
        message += f"请 @{current_player_name} 发送决斗指令"
        await shoot_matcher.send(message)
        return  # 添加return语句，确保在进入下一局后不会继续执行
    
    # 发送回合结束消息
    challenger_name = await get_member_info(bot, event.group_id, int(current_duel.challenger_id))
    target_name = await get_member_info(bot, event.group_id, int(current_duel.target_id))
    next_player_name = await get_member_info(bot, event.group_id, int(current_duel.current_player))
    # 检查下一个玩家是否被手铐禁锢
    if current_duel.handcuff_skip and current_duel.handcuffed_player == current_duel.current_player:
        # 获取被禁锢玩家的名字
        handcuffed_player_name = await get_member_info(bot, event.group_id, int(current_duel.handcuffed_player))
        # 重置手铐状态
        current_duel.handcuff_skip = False
        current_duel.handcuffed_player = None
        # 切换到下一个玩家
        current_duel.current_player = current_duel.target_id if current_duel.current_player == current_duel.challenger_id else current_duel.challenger_id
        next_player_name = await get_member_info(bot, event.group_id, int(current_duel.current_player))
        
        message = f"回合结束！\n"
        message += f"目前 @{challenger_name} 的血量为{current_duel.challenger_health}，@{target_name} 的血量为{current_duel.target_health}\n"
        message += f"@{handcuffed_player_name} 被手铐禁锢，本回合跳过\n"
        message += f"请 @{next_player_name} 发送决斗指令"
    else:
        message = f"回合结束！\n"
        message += f"目前 @{challenger_name} 的血量为{current_duel.challenger_health}，@{target_name} 的血量为{current_duel.target_health}\n"
        message += f"请 @{next_player_name} 发送决斗指令"
    await shoot_matcher.send(message)


@use_item_matcher.handle()
async def handle_use_item(event: GroupMessageEvent, item_name: str):
    global current_duel
    user_id = str(event.user_id)
    if not current_duel or not current_duel.started:
        await use_item_matcher.send("当前没有进行中的决斗！")
        return
    if user_id != current_duel.current_player:
        await use_item_matcher.send("还没轮到您的回合！")
        return
    result = current_duel.use_item(user_id, item_name)
    await use_item_matcher.send(result)




@query_affection_matcher.handle()
async def handle_query_affection(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await query_affection_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    girlfriends = db.get_girlfriends(user_id)
    if not girlfriends:
        await query_affection_matcher.send("您还没有干员！")
        return
    # 按好感度排序，取前10名
    sorted_gfs = sorted(girlfriends, key=lambda x: x["affection"], reverse=True)[:10]
    message = "您目前所有干员的好感度为：\n"
    for gf in sorted_gfs:
        message += f"{gf['name']} {gf['affection']}\n"
    await query_affection_matcher.send(message.strip())




@specific_affection_matcher.handle()
async def handle_specific_affection(event: GroupMessageEvent, partner_name: str):  # 修改参数名
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await specific_affection_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    operators = db.get_girlfriends(user_id)  # 保持数据库函数名不变
    for gf in operators:
        if gf["name"] == partner_name:
            operator_rarity = OPERATOR_RARITY.get(partner_name, 3)
            await specific_affection_matcher.send(f"{operator_rarity}★干员{partner_name}目前对您的好感度为{gf['affection']}")
            return
    await specific_affection_matcher.send("您没有这个干员！")




# 礼物赠送指令定义
@gift_matcher.handle()
async def handle_gift(event: GroupMessageEvent, gift_name: str, partner_name: str):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await gift_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    # 检查礼物是否存在
    if gift_name not in GIFTS:
        await gift_matcher.send("不存在这个礼物！")
        return
    # 检查是否拥有该礼物
    gift_quantity = db.get_gift_quantity(user_id, gift_name)
    if gift_quantity <= 0:
        await gift_matcher.send(f"您没有{gift_name}这个礼物！")
        return
    # 检查是否有该干员
    girlfriends = db.get_girlfriends(user_id)
    target_gf = None
    for gf in girlfriends:
        if gf["name"] == partner_name:
            target_gf = gf
            break
    if not target_gf:
        await gift_matcher.send("您没有这个干员！")
        return
    
    try:
        # 赠送礼物
        success = db.update_gift_quantity(user_id, gift_name, -1)  # 减少礼物数量
        if not success:
            await gift_matcher.send("赠送礼物失败，请稍后重试。")
            return
        db.update_affection(user_id, partner_name, GIFTS[gift_name]["affection"])  # 增加好感度
        # 获取干员星级
        operator_rarity = OPERATOR_RARITY.get(partner_name, 3)
        # 获取更新后的礼物数量
        new_quantity = db.get_gift_quantity(user_id, gift_name)
        await gift_matcher.send(f"赠送成功！\n{operator_rarity}★干员{partner_name}的好感度增加了{GIFTS[gift_name]['affection']}点\n您还剩余{new_quantity}个{gift_name}")
    except Exception as e:
        print(f"Error in gift giving: {e}")
        await gift_matcher.send("赠送礼物时发生错误，请稍后重试。")




@query_gifts_matcher.handle()
async def handle_query_gifts(event: GroupMessageEvent):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await query_gifts_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    gifts = db.get_all_gifts(user_id)
    if not gifts:
        await query_gifts_matcher.send("您尚未持有礼物，可通过指令'购买礼物+礼物名'来购买礼物")
        return
    # 合并相同礼物名的数量
    gift_dict = {}
    for gift in gifts:
        if gift['name'] in gift_dict:
            gift_dict[gift['name']] += gift['quantity']
        else:
            gift_dict[gift['name']] = gift['quantity']
    
    # 按礼物名称排序
    sorted_gifts = sorted(gift_dict.items())
    message = "您当前持有的礼物：\n"
    message += "━━━━━━━━━━\n"
    for gift_name, quantity in sorted_gifts:
        message += f"• {gift_name} × {quantity}\n"
    message += "━━━━━━━━━━"
    await query_gifts_matcher.send(message)


@dismiss_matcher.handle()  # 修改函数名
async def handle_dismiss(event: GroupMessageEvent, partner_name: str):  # 修改函数名和参数名
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await dismiss_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    if user["coins"] < 200:
        await dismiss_matcher.send("您的金币不足，解雇需要200金币")
        return
    if db.remove_girlfriend(user_id, partner_name):  # 保持数据库函数名不变
        db.update_user(user_id, coins=user["coins"] - 200)
        operator_rarity = OPERATOR_RARITY.get(partner_name, 3)
        await dismiss_matcher.send(f"解雇成功，已解雇{operator_rarity}★干员{partner_name}，扣除200金币")
    else:
        await dismiss_matcher.send("您尚未招募该干员")


@buy_gift_matcher.handle()
async def handle_buy_gift(event: GroupMessageEvent, gift_name: str):
    user_id = str(event.user_id)
    user = db.get_user(user_id)
    if not user:
        await buy_gift_matcher.send("您还未在本群创建过贵族，请发送'创建贵族'开始您的贵族之旅。")
        return
    if gift_name not in GIFTS:
        await buy_gift_matcher.send("不存在这个礼物！")
        return
    cost = GIFTS[gift_name]["cost"]
    if user["coins"] < cost:
        await buy_gift_matcher.send(f"很抱歉，您的金币不足，购买{gift_name}需要{cost}金币")
        return
    
    try:
        # 先扣除金币
        db.update_user(user_id, coins=user["coins"] - cost)
        # 再添加礼物
        success = db.update_gift_quantity(user_id, gift_name, 1)
        if not success:
            # 如果添加礼物失败，退还金币
            db.update_user(user_id, coins=user["coins"])
            await buy_gift_matcher.send("购买失败，请稍后重试。")
            return
        current_quantity = db.get_gift_quantity(user_id, gift_name)
        await buy_gift_matcher.send(f"购买成功，花费{cost}金币，您目前持有{current_quantity}个{gift_name}")
    except Exception as e:
        print(f"Error buying gift: {e}")
        # 发生错误时退还金币
        db.update_user(user_id, coins=user["coins"])
        await buy_gift_matcher.send("购买失败，请稍后重试。")


@item_intro_matcher.handle()  # 修改函数名
async def handle_item_intro(event: GroupMessageEvent):  # 修改函数名
    message = "礼物列表：\n"
    for gift_name, config in GIFTS.items():
        message += f"{gift_name}：增加{config['affection']}好感，价格{config['cost']}金币\n"
    message += "\n道具列表：\n"
    for item_name, config in ITEMS.items():
        message += f"{item_name}：{config['description']}\n"
    
    await item_intro_matcher.send(message.strip())


@query_items_matcher.handle()
async def handle_query_items(event: GroupMessageEvent):
    global current_duel
    user_id = str(event.user_id)
    if not current_duel or not current_duel.started:
        await query_items_matcher.send("当前没有进行中的决斗！")
        return
    if user_id not in [current_duel.challenger_id, current_duel.target_id]:
        await query_items_matcher.send("只有决斗中的玩家才能查询道具！")
        return
    # 获取用户当前持有的道具
    items = current_duel.challenger_items if user_id == current_duel.challenger_id else current_duel.target_items
    if not items:
        await query_items_matcher.send("您当前没有持有任何道具！")
        return
    # 获取用户昵称
    from nonebot import get_bot
    bot = get_bot()
    user_name = await get_member_info(bot, event.group_id, int(user_id))
    message = f"@{user_name} 您目前持有道具：\n"
    for item in items:
        message += f"{item}：{ITEMS[item]['description']}\n"
    await query_items_matcher.finish(message.strip())


@reset_duel_matcher.handle()
async def handle_reset_duel(event: GroupMessageEvent):
    global current_duel, bet_players
    # 清空下注记录，不扣除金币
    bet_players = {}
    current_duel = None
    await reset_duel_matcher.send("决斗已重置")


@recharge_coins_matcher.handle()
async def handle_recharge_coins(event: GroupMessageEvent, target: At, amount: int):
    user_id = str(event.user_id)
    target_id = extract_user_id(target)
    # 检查是否是群主
    from nonebot import get_bot
    bot = get_bot()
    try:
        member_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id)
        if member_info.get("role") != "owner":
            await recharge_coins_matcher.finish("只有群主才能使用充值功能！")
            return
    except:
        await recharge_coins_matcher.finish("获取群成员信息失败！")
        return
    # 检查目标用户是否存在
    target_user = db.get_user(target_id)
    if not target_user:
        await recharge_coins_matcher.finish("目标用户还未创建贵族！")
        return
    # 检查充值金额是否为正数
    if amount <= 0:
        await recharge_coins_matcher.finish("充值金额必须为正数！")
        return
    # 执行充值
    new_coins = target_user["coins"] + amount
    db.update_user(target_id, coins=new_coins)
    # 获取目标用户昵称
    target_name = await get_member_info(bot, event.group_id, int(target_id))
    await recharge_coins_matcher.finish(f"充值成功！已为 @{target_name} 充值 {amount} 金币，当前金币余额：{new_coins}")


@help_matcher.handle()
async def handle_help(event: GroupMessageEvent):
    message = """贵族决斗游戏指令帮助：
基础指令：
• 创建贵族 - 创建您的贵族身份
• 贵族查询 - 查看个人信息
• 贵族签到 - 每日签到获得奖励
• 升级爵位 - 提升爵位等级
• 贵族排行 - 查看群内贵族排行榜
干员系统：
• 招募干员 - 花费300金币招募干员
• 干员查询 - 查看拥有的干员列表
• 好感度查询 - 查看干员好感度排行
• 好感度查询 干员名 - 查看特定干员好感度
• 解雇 干员名 - 解雇干员（需200金币）
礼物系统：
• 购买礼物 礼物名 - 购买礼物
• 礼物查询 - 查看拥有的礼物
• 道具介绍 - 查看所有礼物和道具信息
• 礼物 礼物名 干员名 - 赠送礼物给干员（例如：礼物 玩偶 闪灵）
决斗系统：
• 贵族决斗 @用户 - 发起决斗
• 接受决斗 / 拒绝决斗 - 回应决斗邀请
• 下注 @用户 - 对决斗玩家下注
• 开枪 @目标 - 决斗中开枪
• 使用道具 道具名 - 使用决斗道具
• 道具查询 - 查看当前持有的道具
• 重置决斗 - 重置当前决斗
管理员指令：
• 充值金币 @用户 数量 - 为指定用户充值金币（仅群主可用）"""
    await help_matcher.finish(message)