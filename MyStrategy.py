from model.ActionType import ActionType
from model.Game import Game
from model.Move import Move
from model.Wizard import Wizard
from model.World import World
from model.Faction import Faction
from enum import Enum
from math import hypot
import random


class Point2D:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    x = property(lambda self: self._x)
    y = property(lambda self: self._y)

    def distance_to(self, point):
        return hypot(point.x - self.x, point.y - self.y)


class LaneType(Enum):
    TOP = 1
    MIDDLE = 2
    BOTTOM = 3


class MyStrategy:
    WAYPOINT_RADIUS = 100.0
    LOW_HP_FACTOR = 0.25

    def __init__(self):
        self._firsttime = True
        self._waypoints_by_lane = {}
        self._waypoints = []
        self._lane = None
        self._me = None
        self._world = None
        self._game = None
        self._move = None

    def move(self, me: Wizard, world: World, game: Game, move: Move):
        self._initialize_tick(me, world, game, move)
        self._initialize_strategy()

        if random.random() > 0.5:
            move.strafe_speed = game.wizard_strafe_speed
        else:
            move.strafe_speed = -game.wizard_strafe_speed

        if self._me.life < self._me.max_life * MyStrategy.LOW_HP_FACTOR:
            self._go_to(self._previous_waypoint())
            return

        nearest_target, dist = self._get_nearest_target()

        if nearest_target and dist <= self._me.cast_range:
            angle = self._me.get_angle_to_unit(nearest_target)
            self._move.turn = angle

            if abs(angle) < self._game.staff_sector / 2.0:
                self._move.action = ActionType.MAGIC_MISSILE
                self._move.cast_angle = angle
                self._move.min_cast_distance =\
                    dist - nearest_target.radius\
                    + self._game.magic_missile_radius
            return

        self._go_to(self._next_waypoint())

    def _initialize_strategy(self):
        if not self._firsttime:
            return

        random.seed(self._game.random_seed)
        map_size = self._game.map_size

        points = []
        points.append(Point2D(100.0, map_size - 100.0))
        if random.random() > 0.5:
            points.append(Point2D(200.0, map_size - 600.0))
        else:
            points.append(Point2D(600.0, map_size - 200.0))
        points.append(Point2D(800.0, map_size - 800.0))
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

        if self._me.owner_player_id in [1, 2, 6, 7]:
            self._lane = LaneType.TOP
        elif self._me.owner_player_id in [3, 8]:
            self._lane = LaneType.MIDDLE
        elif self._me.owner_player_id in [4, 5, 9, 10]:
            self._lane = LaneType.BOTTOM

        self._waypoints = self._waypoints_by_lane[self._lane]
        self._firsttime = False

    def _initialize_tick(self, me: Wizard, world: World,
                         game: Game, move: Move):
        self._me = me
        self._world = world
        self._game = game
        self._move = move

    def _next_waypoint(self):
        last_wp = self._waypoints[-1]

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

    def _get_nearest_target(self):
        targets = []
        targets.extend(self._world.buildings)
        targets.extend(self._world.wizards)
        targets.extend(self._world.minions)

        nearest_target_distance = 10000.0
        nearest_target = None

        for target in targets:
            if target.faction == Faction.NEUTRAL\
                    or target.faction == self._me.faction:
                continue

            dist = self._me.get_distance_to_unit(target)
            if dist < nearest_target_distance:
                nearest_target_distance = dist
                nearest_target = target
        return nearest_target, nearest_target_distance

    def _go_to(self, point: Point2D):
        angle = self._me.get_angle_to(point.x, point.y)
        self._move.turn = angle

        if abs(angle) < self._game.staff_sector / 4.0:
            self._move.speed = self._game.wizard_forward_speed
