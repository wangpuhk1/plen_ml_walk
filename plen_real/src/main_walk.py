#!/usr/bin/env python
# IMPORTS
import numpy as np
from plen_real.servo_model import ServoJoint
from plen_real.pixel_to_xyz import PixelToXYZ
from plen_real.socket_comms import Socket
from plen_real.imu import IMU
import time


class PlenReal:
    def __init__(self):

        print("Initializing PLEN")

        self.socket = Socket()

        print("Socket Ready!")

        self.joint_names = [
            'rb_servo_r_hip', 'r_hip_r_thigh', 'r_thigh_r_knee',
            'r_knee_r_shin', 'r_shin_r_ankle', 'r_ankle_r_foot',
            'lb_servo_l_hip', 'l_hip_l_thigh', 'l_thigh_l_knee',
            'l_knee_l_shin', 'l_shin_l_ankle', 'l_ankle_l_foot',
            'torso_r_shoulder', 'r_shoulder_rs_servo', 're_servo_r_elbow',
            'torso_l_shoulder', 'l_shoulder_ls_servo', 'le_servo_l_elbow'
        ]

        self.env_ranges = [
            [-1.57, 1.57],  # RIGHT LEG
            [-0.15, 1.5],
            [-0.95, 0.75],
            [-0.9, 0.3],
            [-0.95, 1.2],
            [-0.8, 0.4],
            [-1.57, 1.57],  # LEFT LEG
            [-1.5, 0.15],
            [-0.75, 0.95],
            [-0.3, 0.9],
            [-1.2, 0.95],
            [-0.4, 0.8],
            [-1.57, 1.57],  # RIGHT ARM
            [-0.15, 1.57],
            [-0.2, 0.35],
            [-1.57, 1.57],  # LEFT ARM
            [-0.15, 1.57],
            [-0.2, 0.35]
        ]

        self.joint_list = []

        for i in range(len(self.joint_names)):
            if i < 8:
                # Use ADC 1, gpio 22
                self.joint_list.append(
                    ServoJoint(name=self.joint_names[i],
                               gpio=22,
                               fb_chan=i,
                               pwm_chan=i))
            else:
                # Use ADC 2, gpio 27
                self.joint_list.append(
                    ServoJoint(name=self.joint_names[i],
                               gpio=27,
                               fb_chan=i - 8,
                               pwm_chan=i - 8))

        self.torso_z = 0
        self.torso_y = 0
        self.torso_roll = 0
        self.torso_pitch = 0
        self.torso_yaw = 0
        self.torso_vx = 0

        print("PRESS ENTER TO CALIBRATE IMU")
        self.imu = IMU()

        print("PLEN READY TO GO!")

        self.time = time.time()

    def reset(self):
        self.episode_num += 1
        self.moving_avg_counter += 1
        self.cumulated_episode_reward = 0
        self.episode_timestep = 0
        # Reset Gait Params
        self.gait_period_counter = 0
        self.double_support_preriod_counter = 0
        self.right_contact_counter = 0
        self.left_contact_counter = 0
        self.lhip_joint_angles = np.array([])
        self.rhip_joint_angles = np.array([])
        self.lknee_joint_angles = np.array([])
        self.rknee_joint_angles = np.array([])
        self.lankle_joint_angles = np.array([])
        self.rankle_joint_angles = np.array([])
        print("PICK PLEN OFF THE GROUND AND HOLD IT BY THE TORSO.\n")
        input("PRESS ENTER TO RESET PLEN'S JOINTS TO ZERO.")

        for joint in self.joint_list:
            joint.actuate(0.0)

        input("PUT PLEN ON THE GROUND, PRESS ENTER TO CALIBRATE IMU")
        self.imu.calibrate()

    def step(self, action):
        # Convert agent actions into real actions
        env_action = np.zeros(18)
        # print("MESS {}".format(env_action))

        for i in range(len(action)):
            # Convert action from [-1, 1] to real env values
            env_action[i] = self.agent_to_env(self.env_ranges[i], action[i])

        for j in range(len(self.joint_list)):
            self.joint_list[i].actuate(env_action[i])

        observation = self.compute_observation()
        done = self.compute_done()
        reward = 0
        # reward = self.compute_reward()
        self.cumulated_episode_reward += reward
        self.episode_timestep += 1
        self.total_timesteps += 1
        # Increment Gait Reward Counters
        self.gait_period_counter += 1

        return observation, reward, done, {}

    def compute_done(self):
        """
        Decide if episode is done based on the observations

            - Pitch is above or below pi/2
            - Roll is above or below pi/2
            - Height is below height thresh
            - y position (abs) is above y thresh
            - episode timesteps above limit
        """
        if self.torso_roll > np.abs(np.pi / 3.) or self.torso_pitch > np.abs(
                np.pi / 3.) or self.torso_z < 0.08 or self.torso_y > 1:
            done = True
        else:
            done = False
        return done

    def compute_observation(self):
        # print(len(left_contact))

        self.left_contact = 0
        self.right_contact = 0

        # POSITION AND VELOCITY
        socket_msg = self.socket.receive_message()
        self.torso_y = socket_msg[1]
        self.torso_z = socket_msg[2]
        curr_time = time.time()
        self.torso_vx = (self.torso_x - socket_msg[0]) / float(curr_time -
                                                               self.time)
        self.torso_x = socket_msg[0]

        self.time = time.time()

        # ORIENTATION
        # Filter IMU
        self.imu.filter_rpy()
        # Read IMU
        self.imu.read_imu()
        self.torso_roll = self.imu.roll
        self.torso_pitch = self.imu.pitch
        self.torso_yaw = self.imu.yaw

        # JOINT STATES
        self.joint_poses = []
        for i in range(len(self.joint_list)):
            self.joint_poses = np.append(self.joint_poses,
                                         self.joint_list[i].measure())

        observations = np.append(
            self.joint_poses,
            np.array([
                self.torso_z, self.torso_vx, self.torso_roll, self.torso_pitch,
                self.torso_yaw, self.torso_y, self.right_contact,
                self.left_contact
            ]))

        # Populate Joint Angle Difference Arrays using current - prev
        if len(self.lhip_joint_angles) > 0:
            # thigh_knee in URDF
            self.lhip_joint_angle_diff = self.lhip_joint_angles[
                -1] - self.joint_poses[2]
            self.rhip_joint_angle_diff = self.rhip_joint_angles[
                -1] - self.joint_poses[8]
            # knee_shin in URDF
            self.lknee_joint_angle_diff = self.lknee_joint_angles[
                -1] - self.joint_poses[3]
            self.rknee_joint_angle_diff = self.rknee_joint_angles[
                -1] - self.joint_poses[9]
            # shin_ankle in URDF
            self.lankle_joint_angle_diff = self.lankle_joint_angles[
                -1] - self.joint_poses[4]
            self.rankle_joint_angle_diff = self.rankle_joint_angles[
                -1] - self.joint_poses[10]
            self.first_pass = False
        else:
            self.first_pass = True
            self.lhip_joint_angle_diff = 0
            self.rhip_joint_angle_diff = 0
            self.lknee_joint_angle_diff = 0
            self.rknee_joint_angle_diff = 0
            self.lankle_joint_angle_diff = 0
            self.rankle_joint_angle_diff = 0

        # Pupulate joint angle arrays for gait calc
        # thigh_knee in URDF
        self.lhip_joint_angles = np.append(self.lhip_joint_angles,
                                           self.joint_poses[2])
        self.rhip_joint_angles = np.append(self.rhip_joint_angles,
                                           self.joint_poses[8])
        # knee_shin in URDF
        self.lknee_joint_angles = np.append(self.lknee_joint_angles,
                                            self.joint_poses[3])
        self.rknee_joint_angles = np.append(self.rknee_joint_angles,
                                            self.joint_poses[9])
        # shin_ankle in URDF
        self.lankle_joint_angles = np.append(self.lankle_joint_angles,
                                             self.joint_poses[4])
        self.rankle_joint_angles = np.append(self.rankle_joint_angles,
                                             self.joint_poses[10])

        return observations

    def agent_to_env(self, env_range, agent_val):
        """ Convert an action from the Agent space ([-1, 1])
            to the Environment Space
        """
        # Convert using y = mx + b
        agent_range = [-1, 1]
        # m = (y1 - y2) / (x1 - x2)
        m = (env_range[1] - env_range[0]) / (agent_range[1] - agent_range[0])
        # b = y1 - mx1
        b = env_range[1] - (m * agent_range[1])
        env_val = m * agent_val + b

        # Make sure no out of bounds
        if env_val >= env_range[1]:
            env_val = env_range[1] - 0.001
            # print("Sampled Too High!")
        elif env_val <= env_range[0]:
            env_val = env_range[0] + 0.001
            # print("Sampled Too Low!")

        return env_val