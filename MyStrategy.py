from model.ActionType import ActionType
from model.Game import Game
from model.Move import Move
from model.Wizard import Wizard
from model.World import World
from model.Faction import Faction
import model
from model.SkillType import SkillType
from model.Tree import Tree
from model.MinionType import MinionType
from model.Building import Building
from model.BuildingType import BuildingType
from model.Minion import Minion
from model.Unit import Unit
from model.LivingUnit import LivingUnit
from enum import Enum
from math import hypot
from math import pi
import math
import random

class Point2D:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    x = property(lambda self: self._x)
    y = property(lambda self: self._y)

    def distance_to(self, point):
        return hypot(point.x - self.x, point.y - self.y)

    def __str__(self):
        return "x: {0}, y: {1}".format(self.x, self.y)


class LaneType(Enum):
    TOP = 1
    MIDDLE = 2
    BOTTOM = 3

class UnitInfo:
    def __init__(self, unit: Unit, distance: float, angle: float):
        self._unit = unit
        self._distance = distance
        self._angle = angle

    unit = property(lambda self: self._unit)
    distance = property(lambda self: self._distance)
    angle = property(lambda self: self._angle)

    @unit.setter
    def unit(self, value):
        self._unit = value

    @distance.setter
    def distance(self, value):
        self._distance = value

    @angle.setter
    def angle(self, value):
        self._angle = value

class EnemyInfo():
    def __init__(self, unit_info: UnitInfo, priority: int):
        self._unit_info = unit_info
        self._priority = priority

    unit_info = property(lambda self: self._unit_info)
    priority = property(lambda self: self._priority)

    @unit_info.setter
    def unit_info(self, value):
        self._unit_info = value

    @priority.setter
    def priority(self, value):
        self._priority = value

class MyStrategy:
    WAYPOINT_RADIUS = 100.0
    LOW_HP_FACTOR = 0.4

    PRIORITY_ENEMY_PERIOD = 50

    WIZARD_PRIORITY = 3
    MINION_PRIORITY = 1
    BULDING_PRIORITY = 2
    HEALTH_PRIORITY_DEFAULT = 1
    HEALTH_PRIORITY_BELOW_50 = 2
    HEALTH_PRIORITY_BELOW_25 = 3
    CLOSE_ENEMY_PRIORITY = 5

    def __init__(self):
        self._firsttime = True
        self._waypoints_by_lane = {}
        self._waypoints = []
        self._lane = None
        self._me = None
        self._world = None
        self._game = None
        self._move = None
        self._enemy_locked_tick = 0
        self._last_enemy = None
        self._is_moving = False
        self._prev_location = None
        self._prev_location_tick = 0
        self._current_strafe = 0
        self._current_speed = 0
        self._is_escaping_stuck = False
        self._is_attacking = False
        self._is_falling_back = False
        self._has_frostbolt = False
        self._last_frostbolt_tick = 0
        self._is_attacking_tree = False
        self._is_low_hp = False
        self._nearest_range_enemy = None # tuple (unit, dist, priority)
        self._build_sequence = [
            SkillType.MAGICAL_DAMAGE_BONUS_PASSIVE_1,
            SkillType.MAGICAL_DAMAGE_BONUS_AURA_1,
            SkillType.MAGICAL_DAMAGE_BONUS_PASSIVE_2,
            SkillType.MAGICAL_DAMAGE_BONUS_AURA_2,
            SkillType.FROST_BOLT,
            SkillType.RANGE_BONUS_PASSIVE_1,
            SkillType.RANGE_BONUS_AURA_1,
            SkillType.RANGE_BONUS_PASSIVE_2,
            SkillType.RANGE_BONUS_AURA_2,
            SkillType.ADVANCED_MAGIC_MISSILE,
            SkillType.MAGICAL_DAMAGE_ABSORPTION_PASSIVE_1,
            SkillType.MAGICAL_DAMAGE_ABSORPTION_AURA_1,
            SkillType.MAGICAL_DAMAGE_ABSORPTION_PASSIVE_2,
            SkillType.MAGICAL_DAMAGE_ABSORPTION_AURA_2,
            SkillType.SHIELD
            ]
        self._current_level = 0

        self._priority_enemy = None
        self._last_priority_enemy = None
        self._last_priority_enemy_tick = 0
        self._turn_angle = 0.0
        self._enemy_faction = None
        self._is_in_enemy_range = False
        self._next_wt = 0

    def _tick_diff(self, prev_tick):
        return self._world.tick_index - prev_tick

    def _clear_state(self):
        self._priority_enemy = None
        self._is_attacking = False
        self._turn_angle = 0.0
        self._is_falling_back = False
        self._is_in_enemy_range = False
        self._is_low_hp = False

    def _check_in_enemy_range(self, unit_info: UnitInfo):
        unit = unit_info.unit
        if unit.faction != self._enemy_faction:
            return

        t = type(unit)
        attack_range = 0.0
        if t is Wizard:
            attack_range = unit.cast_range
        elif t is Building:
            if unit.type == BuildingType.FACTION_BASE:
                attack_range = self._game.guardian_tower_attack_range
            else:
                attack_range = self._game.faction_base_attack_range
        elif t is Minion and unit.type == MinionType.FETISH_BLOWDART:
            attack_range = self._game.fetish_blowdart_attack_range
        else:
            return

        if unit_info.distance < attack_range * 1.1:
            self._is_in_enemy_range = True

    def _update_priority_enemy(self, unit_info: UnitInfo):
        unit = unit_info.unit

        if unit.faction != self._enemy_faction:
            return

        if unit_info.distance < self._me.cast_range * 0.6:
            self._is_falling_back = True

        # Не меняем слишком часто противника, чтобы не вертеться от
        # одного к другому.
        if self._last_priority_enemy\
                and self._tick_diff(self._last_priority_enemy_tick)\
                < MyStrategy.PRIORITY_ENEMY_PERIOD:
            if unit.id == self._last_priority_enemy.unit_info.unit.id:
                self._last_priority_enemy.unit_info.distance = unit_info.distance
                self._last_priority_enemy.unit_info.angle = unit_info.angle
                self._priority_enemy = self._last_priority_enemy
        else:
            if unit_info.distance > self._me.cast_range:
                return

            unit_priority = MyStrategy.WIZARD_PRIORITY
            t = type(unit)
            if t is Building:
                unit_priority = MyStrategy.BULDING_PRIORITY
            elif t is Minion:
                unit_priority = MyStrategy.MINION_PRIORITY

            priority = unit_priority * MyStrategy.HEALTH_PRIORITY_DEFAULT
            life_factor = float(unit.life) / unit.max_life
            if life_factor < 0.5:
                priority = unit_priority * MyStrategy.HEALTH_PRIORITY_BELOW_50
            if life_factor < 0.25:
                priority = unit_priority * MyStrategy.HEALTH_PRIORITY_BELOW_25

            if unit_info.distance < self._me.radius + unit.radius * 5:
                #print("close enemy! t:", t )
                priority *= MyStrategy.CLOSE_ENEMY_PRIORITY * unit_info.distance

            enemy = EnemyInfo(unit_info, priority)
            if not self._priority_enemy:
                self._priority_enemy = enemy
            elif self._priority_enemy.priority < priority:
                self._priority_enemy = enemy

            self._last_priority_enemy = self._priority_enemy
            self._last_priority_enemy_tick = self._world.tick_index

    def _update_units(self):
        all_units = []
        all_units.extend(self._world.wizards)
        all_units.extend(self._world.minions)
        all_units.extend(self._world.buildings)
        all_units.extend(self._world.trees)
        all_units.extend(self._world.bonuses)

        for unit in all_units:
            if unit.id == self._me.id:
                continue
            distance = self._me.get_distance_to_unit(unit)
            angle = self._me.get_angle_to_unit(unit)
            unit_info = UnitInfo(unit, distance, angle)

            self._update_priority_enemy(unit_info)
            self._check_in_enemy_range(unit_info)

    def _apply_state(self):
        self._move.turn = self._turn_angle
        self._move.speed = self._current_speed
        self._move.strafe_speed = self._current_strafe

    def _attack(self):
        if not self._priority_enemy:
            return

        self._is_attacking = True
        unit_info = self._priority_enemy.unit_info
        self._turn_angle = unit_info.angle

        if abs(self._turn_angle) < self._game.staff_sector / 2.0:
            if self._has_frostbolt\
                    and self._tick_diff(self._last_frostbolt_tick)\
                    > self._game.frost_bolt_cooldown_ticks:
                self._move.action = ActionType.FROST_BOLT
                self._last_frostbolt_tick = self._world.tick_index
            else:
                self._move.action = ActionType.MAGIC_MISSILE
            self._move.cast_angle = self._turn_angle
            self._move.min_cast_distance = \
                unit_info.distance - unit_info.unit.radius \
                + self._game.magic_missile_radius

    def move(self, me: Wizard, world: World, game: Game, move: Move):
        self._initialize_tick(me, world, game, move)
        self._initialize_strategy()

        self._clear_state()

        self._update_units()

        self._detect_stuck()

        self._attack()

        if self._me.life < self._me.max_life * MyStrategy.LOW_HP_FACTOR:
            if self._is_in_enemy_range:
                self._is_low_hp = True

        if self._is_low_hp or self._is_falling_back:
            self._go_to_no_turn(self._previous_waypoint(), back=True)
        else:
            self._go_to_no_turn(self._next_waypoint(), back=False)

        self._level_up()

        self._apply_state()

    def _level_up(self):
        if self._me.level > self._current_level\
                and self._me.level <= len(self._build_sequence):
            self._move.skill_to_learn = self._build_sequence[self._current_level]
            if self._move.skill_to_learn == SkillType.FROST_BOLT:
                self._has_frostbolt = True
            self._current_level += 1

    def _initialize_strategy(self):
        if not self._firsttime:
            return

        random.seed(self._game.random_seed)
        #random.seed(self._game.random_seed)
        map_size = self._game.map_size

        if self._me.faction == Faction.ACADEMY:
            self._enemy_faction = Faction.RENEGADES
        else:
            self._enemy_faction = Faction.ACADEMY

        self._prev_location = Point2D(self._me.x, self._me.y)
        self._prev_location_tick = self._world.tick_index

        # Вычисляет, с какой стороны от центральной диагонали появился игрок.
        # Считает угол между осью x и игроком, если больше 45 градусов,
        # то слева и наоборот.
        def _is_left_side(x, y):
            v1 = (1, 0)
            v2 = (x, y)
            v1v2 = x
            v2_len = hypot(x, y)
            angle = math.acos(v1v2 / v2_len)
            if angle >= 0.785398:
                return True
            return False

        points = []
        #points.append(Point2D(100.0, map_size - 100.0))
        if _is_left_side(self._me.x, self._me.y):
            points.append(Point2D(150.0, map_size - 300.0))
            points.append(Point2D(200.0, map_size - 600.0))
            points.append(Point2D(600.0, map_size - 600.0))
        else:
            points.append(Point2D(400.0, map_size - 150.0))
            points.append(Point2D(600.0, map_size - 300.0))
            points.append(Point2D(700.0, map_size - 500.0))
        points.append(Point2D(1000.0, map_size - 1000.0))
        points.append(Point2D(2000.0, map_size - 2000.0))
        points.append(Point2D(map_size - 600.0, 600.0))
        self._waypoints_by_lane[LaneType.MIDDLE] = points

        points = []
        #points.append(Point2D(100.0, map_size - 100.0))
        points.append(Point2D(100.0, map_size - 400.0))
        points.append(Point2D(200.0, map_size - 800.0))
        points.append(Point2D(200.0, map_size * 0.75))
        points.append(Point2D(200.0, map_size * 0.5))
        points.append(Point2D(200.0, map_size * 0.25))
        points.append(Point2D(200.0, 200.0))
        points.append(Point2D(map_size * 0.25, 200.0))
        points.append(Point2D(map_size * 0.5, 200.0))
        points.append(Point2D(map_size * 0.75, 200.0))
        points.append(Point2D(map_size - 200.0, 200.0))
        self._waypoints_by_lane[LaneType.TOP] = points

        points = []
        #points.append(Point2D(100.0, map_size - 100.0))
        points.append(Point2D(400.0, map_size - 100.0))
        points.append(Point2D(800.0, map_size - 200.0))
        points.append(Point2D(map_size * 0.25, map_size - 200.0))
        points.append(Point2D(map_size * 0.5, map_size - 200.0))
        points.append(Point2D(map_size * 0.75, map_size - 200.0))
        points.append(Point2D(map_size - 200.0, map_size - 200.0))
        points.append(Point2D(map_size - 200.0, map_size * 0.75))
        points.append(Point2D(map_size - 200.0, map_size * 0.5))
        points.append(Point2D(map_size - 200.0, map_size * 0.25))
        points.append(Point2D(map_size - 200.0, 200.0))
        self._waypoints_by_lane[LaneType.BOTTOM] = points

        if _is_left_side(self._me.x, self._me.y):
            self._lane = random.choice([LaneType.TOP, LaneType.MIDDLE])
        else:
            self._lane = random.choice([LaneType.BOTTOM, LaneType.MIDDLE])
        #self._lane = LaneType.BOTTOM
        self._waypoints = self._waypoints_by_lane[self._lane]
        self._firsttime = False

    def _initialize_tick(self, me: Wizard, world: World,
                         game: Game, move: Move):
        self._me = me
        self._world = world
        self._game = game
        self._move = move

    def _destroy_tree(self, obstacles):
        for obs in obstacles:
            #print("searching tree...")
            #print(type(obs[1]), type(Tree))
            if type(obs[1]) is Tree:
                #print("destroy tree!!!")
                self._turn_angle = obs[0]
                self._is_attacking_tree = True
                if abs(obs[0]) < self._game.staff_sector / 2.0:
                    if obs[2] <= self._game.staff_range:
                        self._move.action = ActionType.STAFF
                    else:
                        self._move.action = ActionType.MAGIC_MISSILE
                    self._move.cast_angle = obs[0]
                    self._move.min_cast_distance = obs[2] - obs[1].radius
                    return
        self._is_attacking_tree = False

    def _calculate_escape_point(self):
        units = list()
        units.extend(self._world.wizards)
        units.extend(self._world.minions)
        units.extend(self._world.buildings)
        units.extend(self._world.trees)
        obstacles = list()
        for unit in units:
            if unit.id == self._me.id:
                continue

            dist = self._me.get_distance_to_unit(unit)
            if dist < self._me.radius + unit.radius * 1.4:
                #print("dist", dist)
                obstacles.append((self._me.get_angle_to_unit(unit), unit, dist))

        obstacles = sorted(obstacles, key=lambda x: x[0])
        obs_num = len(obstacles)
        move_angle = 0.0

        if obs_num == 0:
            return

        self._destroy_tree(obstacles)
        if self._is_attacking_tree:
            return

        if obs_num == 1:
            side = random.choice([-pi / 2, pi / 2])
            move_angle = obstacles[0][0] + side
            if abs(move_angle) > pi:
                if move_angle <= 0.0:
                    move_angle = 2 * pi + move_angle
                else:
                    move_angle = move_angle - 2 * pi
            #print("move", move_angle)
            self._current_speed, self._current_strafe = self._calc_move_to_angle(move_angle)
        else:
            # Прибавление в конец первого элемента, чтобы
            # можно было сравнить их все друг с другом по кругу.
            # При этом изменяется значение угла, вычисляется угол
            # до первого элемента в противоположном направлении.
            if obstacles[0][0] >= 0.0:
                fin_angle = obstacles[0][0] - 2 * pi
            else:
                fin_angle = obstacles[0][0] + 2 * pi
            obstacles.append((fin_angle, obstacles[0][1]))
            for i in range(obs_num):
                angle = abs(obstacles[i][0] - obstacles[i + 1][0])
                #print("angle cur and next!", obstacles[i][0], obstacles[i + 1][0])
                if angle > pi:
                    move_angle = (obstacles[i][0] + obstacles[i + 1][0]) / 2.0
                    #print("move angle!", move_angle)
                    if abs(move_angle) > pi:
                        if move_angle > 0.0:
                            move_angle -= 2 * pi
                        else:
                            move_angle += 2 * pi
                    #print("move angle total!", move_angle)
                    self._current_speed, self._current_strafe = self._calc_move_to_angle(move_angle)
                    break

    def _detect_stuck(self):
        cur_location = Point2D(self._me.x, self._me.y)

        if not self._is_moving:
            return

        if self._tick_diff(self._prev_location_tick) < 20:
            return

        # print("level", self._me.level)
        # print("xp", self._me.xp)

        if cur_location.distance_to(self._prev_location) < 30:
            #print("Escaping!!!")
            #if not self._is_escaping_stuck:
                #print("Escaping!")
            self._is_escaping_stuck = True
            self._calculate_escape_point()
            self._prev_location_tick = self._world.tick_index
            return

        #print("Stop escaping!!!")
        #if self._is_escaping_stuck:
            #print("Stop Escaping!")
        self._is_escaping_stuck = False
        self._current_strafe = 0
        self._current_speed = 0
        self._prev_location = cur_location
        self._prev_location_tick = self._world.tick_index

    # def _next_waypoint(self):
    #     last_wp = self._waypoints[-1]
    #    #print(self._waypoints)

    #     for i in range(len(self._waypoints) - 1):
    #         wp = self._waypoints[i]

    #         if wp.distance_to(Point2D(self._me.x, self._me.y))\
    #                 <= MyStrategy.WAYPOINT_RADIUS:
    #             return self._waypoints[i + 1]

    #         if last_wp.distance_to(wp)\
    #                 < last_wp.distance_to(Point2D(self._me.x, self._me.y)):
    #             return wp
    #     return last_wp

    def _next_waypoint(self):
        min_dist = self._game.map_size
        min_dist_ind = len(self._waypoints) - 1
        for i in range(len(self._waypoints)):
            dist = self._waypoints[i].distance_to(Point2D(self._me.x, self._me.y))
            if dist < min_dist:
                min_dist = dist
                min_dist_ind = i
        if self._next_wt - min_dist_ind > 1:
            self._next_wt = min_dist_ind

        dist = self._waypoints[self._next_wt].distance_to(Point2D(self._me.x, self._me.y))
        if dist < MyStrategy.WAYPOINT_RADIUS:
            self._next_wt += 1

        self._next_wt = self._next_wt % len(self._waypoints)
        return self._waypoints[self._next_wt]

    # def _previous_waypoint(self):
    #     first_wp = self._waypoints[0]

    #     for i in range(len(self._waypoints) - 1, 0, -1):
    #         wp = self._waypoints[i]

    #         if wp.distance_to(Point2D(self._me.x, self._me.y))\
    #                 <= MyStrategy.WAYPOINT_RADIUS:
    #             return self._waypoints[i - 1]

    #         if first_wp.distance_to(wp)\
    #                 < first_wp.distance_to(Point2D(self._me.x, self._me.y)):
    #             return wp
    #     return first_wp

    def _previous_waypoint(self):
        dist = self._waypoints[self._next_wt - 1].distance_to(Point2D(self._me.x, self._me.y))
        if dist < MyStrategy.WAYPOINT_RADIUS:
            self._next_wt -= 1
        if self._next_wt <= 0:
            self._next_wt = 1
        return self._waypoints[self._next_wt - 1]

    def _calc_move_to_angle(self, angle):
        if 0.0 >= angle > (-pi / 2):
            move = self._game.wizard_forward_speed
            strafe = -self._game.wizard_strafe_speed
        elif (-pi / 2) >= angle > -pi:
            move = -self._game.wizard_forward_speed
            strafe = -self._game.wizard_strafe_speed
        elif pi >= angle > pi / 2:
            move = -self._game.wizard_forward_speed
            strafe = self._game.wizard_strafe_speed
        else:
            move = self._game.wizard_forward_speed
            strafe = self._game.wizard_strafe_speed
        return move, strafe

    def _go_to_no_turn(self, point: Point2D, back: bool):
        if not back and self._is_attacking and not self._is_escaping_stuck:
            self._current_strafe = 0
            self._current_speed = 0
            #if self._is_moving:
            #    print("Moving stopped")
            self._is_moving = False
            return

        self._is_moving = True
        angle = self._me.get_angle_to(point.x, point.y)

        if not self._is_attacking and not self._is_escaping_stuck:
            self._turn_angle = angle
            self._current_strafe = 0
            self._current_speed = self._game.wizard_forward_speed
            return

        #if not self._is_moving:
        #    print("Moving started")
        speed, strafe = self._calc_move_to_angle(angle)

        if not self._is_escaping_stuck:
            if not self._is_moving:
                self._prev_location = Point2D(self._me.x, self._me.y)
                self._prev_location_tick = self._world.tick_index
            self._current_strafe = strafe
            self._current_speed = speed

