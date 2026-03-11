import math
import random

import pygame

from game_settings import (
    AGENT_RADIUS,
    DETECTION_RADIUS,
    MAX_FORCE,
    MAX_PLAYERS,
    NPC_PER_TYPE,
    NPC_SPAWN_MIN_DIST,
    PLAYER_ASSIGNMENTS,
    PLAYER_HIGHLIGHTS,
    PLAYER_PUSH_IMPULSE,
    PLAYER_SPEED_MULT,
    POSITIONING_RADIUS,
    POSITIONING_SPEED_MULT,
    PREDATOR_RULES,
    RULES,
    SPEED,
    SPRITE_FORWARD_DEG,
    TYPE_COLORS,
    WIDTH,
    HEIGHT,
    _build_player_spawns,
    _sample_spawn,
    clamp,
)


class Agent:
    def __init__(self, x, y, kind, mobile_id=None, slot_id=None):
        self.pos = pygame.Vector2(x, y)
        self.anchor = pygame.Vector2(x, y)
        self.kind = kind
        self.mobile_id = mobile_id
        self.slot_id = slot_id
        self.vel = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1)).normalize() * SPEED
        self.acc = pygame.Vector2(0, 0)
        self.heading_deg = math.degrees(math.atan2(-self.vel.y, self.vel.x))

    @property
    def is_mobile(self):
        return self.mobile_id is not None

    def _limit_inside(self):
        self.pos.x = clamp(self.pos.x, AGENT_RADIUS, WIDTH - AGENT_RADIUS)
        self.pos.y = clamp(self.pos.y, AGENT_RADIUS, HEIGHT - AGENT_RADIUS)

    def _move_mobile(self, input_vec):
        if input_vec.length() > 1:
            input_vec = input_vec.normalize()
        self.vel = input_vec * (SPEED * PLAYER_SPEED_MULT) if input_vec.length() > 0.03 else self.vel * 0.85
        self.pos += self.vel
        self._limit_inside()

    def _move_ai(self, all_agents):
        target_kind = RULES[self.kind]
        predator_kind = PREDATOR_RULES[self.kind]

        desired = pygame.Vector2(0, 0)
        separation = pygame.Vector2(0, 0)
        nearest_target = None
        nearest_dist = float("inf")
        chased = False

        for other in all_agents:
            if other is self:
                continue
            delta = self.pos - other.pos
            dist = delta.length()
            if dist < 0.1:
                continue

            if dist < AGENT_RADIUS * 3:
                separation += delta.normalize() / dist

            if dist < DETECTION_RADIUS:
                if other.kind == target_kind:
                    desired += (other.pos - self.pos).normalize()
                elif other.kind == predator_kind:
                    desired -= (other.pos - self.pos).normalize()
                    chased = True

            if other.kind == target_kind and dist < nearest_dist:
                nearest_dist = dist
                nearest_target = other

        if desired.length() == 0 and nearest_target:
            desired = (nearest_target.pos - self.pos).normalize()

        boundary = pygame.Vector2(0, 0)
        if chased:
            margin = 100
            if self.pos.x < margin:
                boundary.x = 1
            elif self.pos.x > WIDTH - margin:
                boundary.x = -1
            if self.pos.y < margin:
                boundary.y = 1
            elif self.pos.y > HEIGHT - margin:
                boundary.y = -1

        wander = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1)) * 0.2
        goal = desired + separation * 3 + boundary * 2 + wander

        if goal.length() > 0:
            target_vel = goal.normalize() * SPEED
            steer = target_vel - self.vel
            if steer.length() > MAX_FORCE:
                steer.scale_to_length(MAX_FORCE)
            self.acc += steer

        self.vel += self.acc
        if self.vel.length() > SPEED:
            self.vel.scale_to_length(SPEED)

        self.pos += self.vel
        self.acc *= 0

        if self.pos.x <= AGENT_RADIUS or self.pos.x >= WIDTH - AGENT_RADIUS:
            self.vel.x *= -1
        if self.pos.y <= AGENT_RADIUS or self.pos.y >= HEIGHT - AGENT_RADIUS:
            self.vel.y *= -1
        self._limit_inside()

    def move(self, all_agents, mobile_inputs):
        if self.is_mobile:
            x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
            self._move_mobile(pygame.Vector2(x, y))
        else:
            self._move_ai(all_agents)

    def move_in_test(self, mobile_inputs):
        if not self.is_mobile:
            return
        x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
        self._move_mobile(pygame.Vector2(x, y))

    def move_in_positioning(self, mobile_inputs):
        if not self.is_mobile:
            self.vel = pygame.Vector2(0, 0)
            return

        x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
        input_vec = pygame.Vector2(x, y)
        if input_vec.length() > 1:
            input_vec = input_vec.normalize()

        prep_speed = SPEED * PLAYER_SPEED_MULT * POSITIONING_SPEED_MULT
        if input_vec.length() > 0.03:
            self.vel = input_vec * prep_speed
        else:
            self.vel *= 0.78

        self.pos += self.vel
        offset = self.pos - self.anchor
        if offset.length() > POSITIONING_RADIUS:
            offset.scale_to_length(POSITIONING_RADIUS)
            self.pos = self.anchor + offset
            self.vel *= 0.45

        self._limit_inside()

    def collide_and_convert(self, all_agents):
        for other in all_agents:
            if other is self:
                continue
            delta = self.pos - other.pos
            dist = delta.length()
            if dist >= AGENT_RADIUS * 2:
                continue

            if dist > 0:
                overlap = AGENT_RADIUS * 2 - dist
                n = delta.normalize()
                if self.is_mobile and not other.is_mobile:
                    self_share, other_share = 0.20, 0.80
                    other.vel -= n * PLAYER_PUSH_IMPULSE
                elif not self.is_mobile and other.is_mobile:
                    self_share, other_share = 0.80, 0.20
                    self.vel += n * PLAYER_PUSH_IMPULSE
                else:
                    self_share, other_share = 0.50, 0.50

                self.pos += n * (overlap * self_share)
                other.pos -= n * (overlap * other_share)

            if other.kind == PREDATOR_RULES[self.kind]:
                self.kind = PREDATOR_RULES[self.kind]

    def draw(self, screen, sprites):
        if self.slot_id is not None:
            ring = PLAYER_HIGHLIGHTS[self.slot_id]
            pygame.draw.circle(
                screen,
                ring,
                (int(self.pos.x), int(self.pos.y)),
                AGENT_RADIUS + 6,
                3 if self.is_mobile else 1,
            )

        if self.vel.length() > 0.05:
            self.heading_deg = math.degrees(math.atan2(-self.vel.y, self.vel.x))

        base = sprites[self.kind]
        rotated = pygame.transform.rotate(base, self.heading_deg - SPRITE_FORWARD_DEG[self.kind])
        rect = rotated.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        screen.blit(rotated, rect)


def create_agents(connected_players):
    connected_set = set(connected_players)
    agents = []
    occupied = []
    player_spawns = _build_player_spawns()

    for kind in ("rock", "paper", "scissors"):
        for _ in range(NPC_PER_TYPE):
            sx, sy = _sample_spawn(occupied, NPC_SPAWN_MIN_DIST)
            occupied.append((sx, sy))
            agents.append(
                Agent(
                    sx,
                    sy,
                    kind,
                )
            )

    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = player_spawns[player_id]
        mobile_id = player_id if player_id in connected_set else None
        agents.append(Agent(sx, sy, assignment["type"], mobile_id=mobile_id, slot_id=player_id))

    return agents


def create_positioning_agents(connected_players):
    agents = create_agents(connected_players)
    for agent in agents:
        agent.vel = pygame.Vector2(0, 0)
        agent.acc = pygame.Vector2(0, 0)
    return agents


def create_test_agents(connected_players):
    connected_set = set(connected_players)
    agents = []
    player_spawns = _build_player_spawns()
    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = player_spawns[player_id]
        mobile_id = player_id if player_id in connected_set else None
        agent = Agent(sx, sy, assignment["type"], mobile_id=mobile_id, slot_id=player_id)
        if not agent.is_mobile:
            agent.vel = pygame.Vector2(0, 0)
        agents.append(agent)
    return agents
