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
from model.Minion import Minion
from enum import Enum
from math import hypot
from math import pi
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


class MyStrategy:
    WAYPOINT_RADIUS = 100.0
    LOW_HP_FACTOR = 0.35

    WIZARD_PRIORITY = 3
    MINION_PRIORITY = 1
    BULDING_PRIORITY = 2

    MAX_PRIORITY = 100

    CLOSE_ENEMY_PRIORITY = 5
    HEALTH_PRIORITY_DEFAULT = 1
    HEALTH_PRIORITY_BELOW_50 = 2
    HEALTH_PRIORITY_BELOW_25 = 3

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

    def _get_range_unit_attack_dist(self, unit):
        if type(unit) is Building:
            return unit.attack_range
        elif type(unit) is Wizard:
            return unit.cast_range
        elif type(unit) is Minion\
                and unit.type == MinionType.FETISH_BLOWDART:
            return self._game.fetish_blowdart_attack_range
        else:
            return 0.0

    def move(self, me: Wizard, world: World, game: Game, move: Move):
        self._initialize_tick(me, world, game, move)
        self._initialize_strategy()

        self._detect_stuck()

        self._is_attacking = False
        if self._last_enemy\
                and (self._world.tick_index - self._enemy_locked_tick) < 50:
            self._update_last_enemy()
        else:
            self._is_falling_back = False
            unit_prior = self._get_priority_target()
            self._enemy_locked_tick = self._world.tick_index
            self._last_enemy = unit_prior

        if self._last_enemy:
            self._is_attacking = True
            angle = self._me.get_angle_to_unit(self._last_enemy[0])
            self._move.turn = angle

            if abs(angle) < self._game.staff_sector / 2.0:
                if self._has_frostbolt\
                        and (self._world.tick_index - self._last_frostbolt_tick)\
                        > self._game.frost_bolt_cooldown_ticks:
                    self._move.action = ActionType.FROST_BOLT
                    self._last_frostbolt_tick = self._world.tick_index
                else:
                    self._move.action = ActionType.MAGIC_MISSILE
                self._move.cast_angle = angle
                self._move.min_cast_distance = \
                    self._last_enemy[1] - self._last_enemy[0].radius \
                    + self._game.magic_missile_radius

        if self._me.life < self._me.max_life * MyStrategy.LOW_HP_FACTOR:
            if self._nearest_range_enemy:
                #print("nearest", self._nearest_range_enemy[1], self._get_range_unit_attack_dist(self._nearest_range_enemy[0]))
                if self._nearest_range_enemy[1]\
                        <= self._get_range_unit_attack_dist(self._nearest_range_enemy[0]):
                    self._is_low_hp = True
        else:
            self._is_low_hp = False

        if self._is_low_hp or self._is_falling_back:
            self._go_to_no_turn(self._previous_waypoint(), back=True)
        else:
            self._go_to_no_turn(self._next_waypoint(), back=False)

        self._move.speed = self._current_speed
        self._move.strafe_speed = self._current_strafe
        self._level_up()

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
        map_size = self._game.map_size

        self._prev_location = Point2D(self._me.x, self._me.y)
        self._prev_location_tick = self._world.tick_index

        points = []
        points.append(Point2D(100.0, map_size - 100.0))
        if random.random() > 0.5:
            points.append(Point2D(200.0, map_size - 600.0))
        else:
            points.append(Point2D(600.0, map_size - 200.0))
        points.append(Point2D(800.0, map_size - 800.0))
        #points.append(Point2D(2000.0, map_size - 2000.0))
        points.append(Point2D(map_size - 600.0, 600.0))
        self._waypoints_by_lane[LaneType.MIDDLE] = points

        points = []
        points.append(Point2D(100.0, map_size - 100.0))
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
        points.append(Point2D(100.0, map_size - 100.0))
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

        self._lane = random.choice(list(LaneType))
        #self._lane = LaneType.MIDDLE
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
                self._move.turn = obs[0]
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

        if (self._world.tick_index - self._prev_location_tick) < 20:
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

    def _next_waypoint(self):
        last_wp = self._waypoints[-1]
       #print(self._waypoints)

        for i in range(len(self._waypoints) - 1):
            wp = self._waypoints[i]

            if wp.distance_to(Point2D(self._me.x, self._me.y))\
                    <= MyStrategy.WAYPOINT_RADIUS:
                return self._waypoints[i + 1]

            if last_wp.distance_to(wp)\
                    < last_wp.distance_to(Point2D(self._me.x, self._me.y)):
                return wp
        return last_wp

    def _previous_waypoint(self):
        first_wp = self._waypoints[0]

        for i in range(len(self._waypoints) - 1, 0, -1):
            wp = self._waypoints[i]

            if wp.distance_to(Point2D(self._me.x, self._me.y))\
                    <= MyStrategy.WAYPOINT_RADIUS:
                return self._waypoints[i - 1]

            if first_wp.distance_to(wp)\
                    < first_wp.distance_to(Point2D(self._me.x, self._me.y)):
                return wp
        return first_wp

    def _update_last_enemy(self):
        if type(self._last_enemy[0]) is Building:
            return

        if type(self._last_enemy[0]) is Minion:
            units = self._world.minions
        else:
            units = self._world.wizards

        for unit in units:
            if unit.id == self._last_enemy[0].id:
                dist = self._me.get_distance_to_unit(unit)
                self._last_enemy = (unit, dist, self._last_enemy[2])
                return

    def _arrange_by_priority(self, units):
        if len(units) == 0:
            return list()

        unit_priority = MyStrategy.WIZARD_PRIORITY
        if type(units[0]) is Building:
            unit_priority = MyStrategy.BULDING_PRIORITY
        elif type(units[0]) is Minion:
            unit_priority = MyStrategy.MINION_PRIORITY

        prior_units = list()
        for unit in units:
            if unit.faction == Faction.NEUTRAL\
                    or unit.faction == self._me.faction:
                continue

            dist = self._me.get_distance_to_unit(unit)

            if dist < self._nearest_range_enemy[1]:
                self._nearest_range_enemy = (unit, dist, 0)

            if dist > self._me.cast_range:
                continue

            if dist < self._me.cast_range * 0.8:
                #print("fall back!")
                self._is_falling_back = True

            priority = unit_priority * MyStrategy.HEALTH_PRIORITY_DEFAULT
            life_factor = float(unit.life) / unit.max_life
            if life_factor < 0.5:
                priority = unit_priority * MyStrategy.HEALTH_PRIORITY_BELOW_50
            if life_factor < 0.25:
                priority = unit_priority * MyStrategy.HEALTH_PRIORITY_BELOW_25
            prior_units.append((unit, dist, priority))

            if dist < self._game.wizard_radius + unit.radius * 3:
                priority *= dist * (1 - life_factor)
        return sorted(prior_units, key=lambda x: x[2], reverse=True)

    def _get_priority_target(self):
        self._nearest_range_enemy = (None, self._game.map_size, 0)
        prior_buildings = self._arrange_by_priority(self._world.buildings)
        prior_wizards = self._arrange_by_priority(self._world.wizards)
        prior_minions = self._arrange_by_priority(self._world.minions)

        max_prior = list()
        unit_prior = None
        if prior_buildings:
            max_prior.append(prior_buildings[0])
        if prior_wizards:
            max_prior.append(prior_wizards[0])
        if prior_minions:
            max_prior.append(prior_minions[0])

        if max_prior:
            unit_prior = max(max_prior, key=lambda x: x[2])
        return unit_prior

    # def _go_to(self, point: Point2D):
    #     self._is_moving = True
    #     angle = self._me.get_angle_to(point.x, point.y)
    #     self._move.turn = angle
    #
    #     if abs(angle) < self._game.staff_sector / 4.0:
    #         self._move.speed = self._game.wizard_forward_speed

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

        #if not self._is_moving:
        #    print("Moving started")
        angle = self._me.get_angle_to(point.x, point.y)
        speed, strafe = self._calc_move_to_angle(angle)

        if not self._is_escaping_stuck:
            if not self._is_moving:
                self._prev_location = Point2D(self._me.x, self._me.y)
                self._prev_location_tick = self._world.tick_index
            self._current_strafe = strafe
            self._current_speed = speed

        self._is_moving = True

