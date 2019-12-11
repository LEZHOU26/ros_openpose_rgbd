#!/usr/bin/env python
# -*- coding: utf-8 -*-

import numpy as np
import cv2
import rospy
import argparse
import glob
import time

from lib_draw_3d_joints import Human, set_default_params
from lib_openpose_detector import OpenposeDetector

if True:  # Add project root
    import sys
    import os
    ROOT = os.path.dirname(os.path.abspath(__file__))+'/'
    sys.path.append(ROOT)
    from utils.lib_rgbd import RgbdImage, MyCameraInfo
    from utils.lib_ros_rgbd_pub_and_sub import ColorImageSubscriber, DepthImageSubscriber, CameraInfoSubscriber


def parse_command_line_arguments():

    parser = argparse.ArgumentParser(
        description="Detect human joints and then draw in rviz.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # -- Select data source.
    parser.add_argument("-s", "--data_source",
                        default="disk",
                        choices=["rostopic", "disk"])
    parser.add_argument("-z", "--detect_hand", type=Bool,
                        default=False)
    parser.add_argument("-u", "--depth_unit", type=float,
                        default="0.001",
                        help="Depth is (pixel_value * depth_unit) meters.")

    # -- "rostopic" as data source.
    parser.add_argument("-a", "--ros_topic_color",
                        default="camera/color/image_raw")
    parser.add_argument("-b", "--ros_topic_depth",
                        default="camera/aligned_depth_to_color/image_raw")
    parser.add_argument("-c", "--ros_topic_camera_info",
                        default="camera/color/camera_info")

    # -- "disk" as data source.
    parser.add_argument("-d", "--base_folder",
                        default=ROOT)
    parser.add_argument("-e", "--folder_color",
                        default="data/images40/color/")
    parser.add_argument("-f", "--folder_depth",
                        default="data/images40/depth/")
    parser.add_argument("-g", "--camera_info_file",
                        default="data/images40/cam_params_realsense.json")

    # -- Get args.
    inputs = rospy.myargv()[1:]
    inputs = [s for s in inputs if s.replace(" ", "") != ""]  # Remove blanks.
    args = parser.parse_args(inputs)

    # -- Deal with relative path.
    b = args.base_folder
    args.folder_color = b + args.folder_color
    args.folder_depth = b + args.folder_depth
    args.camera_info_file = b + args.camera_info_file

    # -- Return
    return args


def Bool(v):
    ''' A bool class for argparser '''
    # TODO: Add a reference
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


class DataReader_DISK(object):
    def __init__(self, args):
        self._fcolors = sorted(glob.glob(args.folder_color + "/*"))
        basenames = [os.path.basename(s) for s in self._fcolors]
        self._fdepths = [args.folder_depth + "/" + s for s in basenames]
        self._camera_info = MyCameraInfo(
            camera_info_file_path=args.camera_info_file)
        self._depth_unit = args.depth_unit
        self._cnt_imgs = 0
        self._total_images = len(self._fcolors)

    def total_images(self):
        return self._total_images

    def read_next_data(self):
        def read_img(folders, i):
            return cv2.imread(folders[i], cv2.IMREAD_UNCHANGED)
        color = read_img(self._fcolors, self._cnt_imgs)
        depth = read_img(self._fdepths, self._cnt_imgs)
        self._cnt_imgs += 1
        rgbd = RgbdImage(color, depth,
                         self._camera_info,
                         depth_unit=self._depth_unit)
        return rgbd


class DataReader_ROS(object):
    def __init__(self, args):
        self._sub_c = ColorImageSubscriber(args.ros_topic_color)
        self._sub_d = DepthImageSubscriber(args.ros_topic_depth)
        self._sub_i = CameraInfoSubscriber(args.ros_topic_camera_info)
        self._depth_unit = args.depth_unit
        self._camera_info = None
        self._cnt_imgs = 0

    def _get_camera_info(self):
        '''
        Since camera info usually doesn't change,
        we read it from cache after it's initialized.
        '''
        if self._camera_info is None:
            while (not self._sub_i.has_camera_info()) and (not rospy.is_shutdown):
                rospy.sleep(0.001)
            if self._sub_i.has_camera_info:
                self._camera_info = MyCameraInfo(
                    ros_camera_info=self._sub_i.get_camera_info())
        return self._camera_info

    def total_images(self):
        ''' Set a large number here. '''
        return 9999

    def _read_depth(self):
        while not self._sub_d.has_image() and (not rospy.is_shutdown()):
            rospy.sleep(0.001)
        depth = self._sub_d.get_image()
        return depth

    def _read_color(self):
        while not self._sub_c.has_image() and (not rospy.is_shutdown()):
            rospy.sleep(0.001)
        color = self._sub_c.get_image()
        return color

    def read_next_data(self):
        depth = self._read_depth()
        color = self._read_color()
        camera_info = self._get_camera_info()
        self._cnt_imgs += 1
        rgbd = RgbdImage(color, depth,
                         camera_info,
                         depth_unit=self._depth_unit)
        return rgbd


def main(args):

    # -- Data reader.
    if args.data_source == "disk":
        data_reader = DataReader_DISK(args)
    else:
        data_reader = DataReader_ROS(args)
    ith_image = 0
    total_images = data_reader.total_images()

    # -- Detector.
    detector = OpenposeDetector(
        {"hand": args.detect_hand != 0}
    )

    # -- Settings.
    cam_pose, cam_pose_pub = set_default_params()

    # -- Loop: read, detect, draw.
    prev_humans = []
    while not rospy.is_shutdown() and ith_image < total_images:
        t0 = time.time()

        # -- Read data
        print("============================================")
        rospy.loginfo("Reading {}/{}th color/depth images...".format(
            ith_image+1, total_images))
        rgbd = data_reader.read_next_data()
        rgbd.set_camera_pose(cam_pose)
        ith_image += 1

        # -- Detect joints.
        print("  Detecting joints...")
        body_joints, hand_joints = detector.detect(
            rgbd.color_image(), is_return_joints=True)
        N_people = len(body_joints)

        # -- Delete previous joints.
        for human in prev_humans:
            # If I put delete after drawing new markders,
            # The delete doesn't work. I don't know why.
            human.delete_rviz()

        # -- Draw humans in rviz.
        humans = []
        for i in range(N_people):
            human = Human(rgbd, body_joints[i], hand_joints[i])
            human.draw_rviz()
            rospy.loginfo("  Drawing {}/{}th person with id={} on rviz.".format(
                i+1, N_people, human._id))
            humans.append(human)

        # -- Loop.
        prev_humans = humans
        # Keep update camera pose for rviz visualization.
        cam_pose_pub.publish()
        print("Total time = {} seconds.".format(time.time()-t0))

    # -- Clean up.
    for human in humans:
        human.delete_rviz()


if __name__ == '__main__':
    node_name = "detect_and_draw_joints"
    rospy.init_node(node_name)
    rospy.sleep(0.1)
    args = parse_command_line_arguments()
    main(args)
    rospy.logwarn("Node `{}` stops.".format(node_name))
