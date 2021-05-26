# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import numpy as np

import torch
import torch.nn as nn
import os.path as osp
import os
try:
    import cPickle as pickle
except ImportError:
    import pickle
import cv2

def rel_change(prev_val, curr_val):
    return (prev_val - curr_val) / max([np.abs(prev_val), np.abs(curr_val), 1])

def load_camera_para(file):
    """"
    load camera parameters
    """
    campose = []
    intra = []
    campose_ = []
    intra_ = []
    f = open(file,'r')
    for line in f:
        line = line.strip('\n')
        line = line.rstrip()
        words = line.split()
        if len(words) == 3:
            intra_.append([float(words[0]),float(words[1]),float(words[2])])
        elif len(words) == 4:
            campose_.append([float(words[0]),float(words[1]),float(words[2]),float(words[3])])
        else:
            pass

    index = 0
    intra_t = []
    for i in intra_:
        index+=1
        intra_t.append(i)
        if index == 3:
            index = 0
            intra.append(intra_t)
            intra_t = []

    index = 0
    campose_t = []
    for i in campose_:
        index+=1
        campose_t.append(i)
        if index == 3:
            index = 0
            campose_t.append([0.,0.,0.,1.])
            campose.append(campose_t)
            campose_t = []
    
    return np.array(campose), np.array(intra)

def get_rot_trans(campose, photoscan=False):
    trans = []
    rot = []
    for cam in campose:
        # for photoscan parameters
        if photoscan:
            cam = np.linalg.inv(cam)  
        trans.append(cam[:3,3])
        rot.append(cam[:3,:3])
        # rot.append(cv2.Rodrigues(cam[:3,:3])[0])

    return trans, rot

class JointMapper(nn.Module):
    def __init__(self, joint_maps=None):
        super(JointMapper, self).__init__()
        if joint_maps is None:
            self.joint_maps = joint_maps
        else:
            self.register_buffer('joint_maps',
                                 torch.tensor(joint_maps, dtype=torch.long))

    def forward(self, joints, **kwargs):
        if self.joint_maps is None:
            return joints
        else:
            return torch.index_select(joints, 1, self.joint_maps)


class GMoF(nn.Module):
    def __init__(self, rho=1):
        super(GMoF, self).__init__()
        self.rho = rho

    def extra_repr(self):
        return 'rho = {}'.format(self.rho)

    def forward(self, residual):
        squared_res = residual ** 2
        dist = torch.div(squared_res, squared_res + self.rho ** 2)
        return self.rho ** 2 * dist


def smpl_to_annotation(model_type='smpl', use_hands=False, use_face=False,
                     use_face_contour=False, pose_format='coco17'):

    if pose_format == 'coco17':
        if model_type == 'smpl':
            #coco17 order: Nose Leye Reye Lear Rear LS RS LE RE LW RW LH RH LK RK LA RA
            return np.array([24, 25, 26, 27, 28, 16, 17, 18, 19, 20, 21, 1,
                             2, 4, 5, 7, 8],
                            dtype=np.int32)
        else:
            raise ValueError('Unknown model type: {}'.format(model_type))
    elif pose_format == 'lsp14':
        if model_type == 'smpllsp':
            #lsp order: Nose Leye Reye Lear Rear LS RS LE RE LW RW LH RH LK RK LA RA
            return np.array([14, 15, 16, 17, 18, 9, 8, 10, 7, 11, 6, 3,
                             2, 4, 1, 5, 0],
                            dtype=np.int32)
        else:
            raise ValueError('Unknown model type: {}'.format(model_type))
    else:
        raise ValueError('Unknown joint format: {}'.format(openpose_format))

def project_to_img(joints, verts, faces, gt_joints, camera, image_path, viz=False, path=None):

    d2j = []
    vertices = []
    for cam in camera:
        d2j_ = cam(joints).detach().cpu().numpy().astype(np.int32)
        vert = cam(verts).detach().cpu().numpy().astype(np.int32)
        d2j.append(d2j_)
        vertices.append(vert)

    if viz:
        for v in range(len(image_path)):
            img_dir = image_path[v]
            view = img_dir.split('\\')[-2]
            img = cv2.imread(img_dir)
            for f in faces:
                color = 255
                point = vertices[v][0][f]
                img = cv2.polylines(img,[point],True,(color,color,color),1)
            for p in d2j[v][0]:
                cv2.circle(img, (int(p[0]),int(p[1])), 3, (0,0,255), 10)
            for p in gt_joints[v][0]:
                cv2.circle(img, (int(p[0]),int(p[1])), 3, (0,255,0), 10)

            cv2.imwrite("%s/%s.jpg" %(path, view), img)
        


def save_results(setting, data, result, 
                use_vposer=True, 
                save_meshes=False, save_images=False, 
                **kwargs):
    model_type=kwargs.get('model_type', 'smpl')
    vposer = setting['vposer']
    model = setting['model']
    camera = setting['camera']
    serial = data['serial']
    fn = data['fn']
    img_path = data['img_path']
    keypoints = data['keypoints']
    person_id = 0

    if use_vposer:
        pose_embedding = result['pose_embedding']
        body_pose = vposer.decode(
                pose_embedding, output_type='aa').view(1, -1) if use_vposer else None

        # the parameters of foot and hand are from vposer
        # we do not use this inaccurate results
        if True:
            body_pose[:,18:24] = 0.
            body_pose[:,27:33] = 0.
            body_pose[:,57:] = 0.
        result['body_pose'] = body_pose.detach().cpu().numpy()
        orient = np.array(model.global_orient.detach().cpu().numpy())
        temp_pose = body_pose.detach().cpu().numpy()
        pose = np.hstack((orient,temp_pose))
        result['pose'] = pose
        result['pose_embedding'] = pose_embedding.detach().cpu().numpy()
    else:
        if True:
            result['body_pose'][:,18:24] = 0.
            result['body_pose'][:,27:33] = 0.
            result['body_pose'][:,57:] = 0.
        pose = np.hstack((result['global_orient'],result['body_pose']))
        result['pose'] = pose

    # save results
    curr_result_fn = osp.join(setting['result_folder'], serial, fn)
    if not osp.exists(curr_result_fn):
        os.makedirs(curr_result_fn)
    result_fn = osp.join(curr_result_fn, '{:03d}.pkl'.format(person_id))
    with open(result_fn, 'wb') as result_file:
        pickle.dump(result, result_file, protocol=2)

    if save_meshes or save_images:
        if not use_vposer:
            body_pose = model.body_pose.detach()
            body_pose[:,18:24] = 0.
            body_pose[:,27:33] = 0.
            body_pose[:,57:] = 0.

        model_output = model(return_verts=True, body_pose=body_pose)
        vertices = model_output.vertices.detach().cpu().numpy().squeeze()

        # save image
        if save_images:
            curr_image_fn = osp.join(setting['img_folder'], serial, fn)
            if not osp.exists(curr_image_fn):
                os.makedirs(curr_image_fn)
            body_joints = model_output.joints
            verts = model_output.vertices
            project_to_img(body_joints, verts, model.faces, keypoints, camera, img_path, viz=True, path=curr_image_fn)

        if save_meshes:
            import trimesh
            curr_mesh_fn = osp.join(setting['mesh_folder'], serial, fn)
            if not osp.exists(curr_mesh_fn):
                os.makedirs(curr_mesh_fn)
            mesh_fn = osp.join(curr_mesh_fn, '{:03d}.obj'.format(person_id))
            out_mesh = trimesh.Trimesh(vertices, model.faces, process=False)
            out_mesh.export(mesh_fn)
