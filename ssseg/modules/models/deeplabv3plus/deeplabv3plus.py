'''
Function:
    Implementation of Deeplabv3+
Author:
    Zhenchao Jin
'''
import copy
import torch
import torch.nn as nn
import torch.nn.functional as F
from ...backbones import *
from ..base import BaseModel
from .aspp import DepthwiseSeparableASPP


'''deeplabv3 plus'''
class Deeplabv3Plus(BaseModel):
    def __init__(self, cfg, **kwargs):
        super(Deeplabv3Plus, self).__init__(cfg, **kwargs)
        align_corners, normlayer_opts, activation_opts = self.align_corners, self.normlayer_opts, self.activation_opts
        # build aspp net
        aspp_cfg = {
            'in_channels': cfg['aspp']['in_channels'],
            'out_channels': cfg['aspp']['out_channels'],
            'rates': cfg['aspp']['rates'],
            'align_corners': align_corners,
            'normlayer_opts': copy.deepcopy(normlayer_opts),
            'activation_opts': copy.deepcopy(activation_opts),
        }
        self.aspp_net = DepthwiseSeparableASPP(**aspp_cfg)
        # build shortcut
        shortcut_cfg = cfg['shortcut']
        self.shortcut = nn.Sequential(
            nn.Conv2d(shortcut_cfg['in_channels'], shortcut_cfg['out_channels'], kernel_size=1, stride=1, padding=0, bias=False),
            BuildNormalizationLayer(normlayer_opts['type'], (shortcut_cfg['out_channels'], normlayer_opts['opts'])),
            BuildActivation(activation_opts['type'], **activation_opts['opts'])
        )
        # build decoder
        decoder_cfg = cfg['decoder']
        self.decoder = nn.Sequential(
            DepthwiseSeparableConv2d(decoder_cfg['in_channels'], decoder_cfg['out_channels'], kernel_size=3, stride=1, padding=1, bias=False, activation_opts=activation_opts, normlayer_opts=normlayer_opts),
            DepthwiseSeparableConv2d(decoder_cfg['out_channels'], decoder_cfg['out_channels'], kernel_size=3, stride=1, padding=1, bias=False, activation_opts=activation_opts, normlayer_opts=normlayer_opts),
            nn.Dropout2d(decoder_cfg['dropout']),
            nn.Conv2d(decoder_cfg['out_channels'], cfg['num_classes'], kernel_size=1, stride=1, padding=0)
        )
        # build auxiliary decoder
        auxiliary_cfg = cfg['auxiliary']
        self.auxiliary_decoder = nn.Sequential(
            nn.Conv2d(auxiliary_cfg['in_channels'], auxiliary_cfg['out_channels'], kernel_size=3, stride=1, padding=1, bias=False),
            BuildNormalizationLayer(normlayer_opts['type'], (auxiliary_cfg['out_channels'], normlayer_opts['opts'])),
            BuildActivation(activation_opts['type'], **activation_opts['opts']),
            nn.Dropout2d(auxiliary_cfg['dropout']),
            nn.Conv2d(auxiliary_cfg['out_channels'], cfg['num_classes'], kernel_size=1, stride=1, padding=0)
        )
        # freeze normalization layer if necessary
        if cfg.get('is_freeze_normlayer', False): self.freezenormlayer()
    '''forward'''
    def forward(self, x, targets=None, losses_cfg=None):
        h, w = x.size(2), x.size(3)
        # feed to backbone network
        x1, x2, x3, x4 = self.backbone_net(x)
        # feed to aspp
        aspp_out = self.aspp_net(x4)
        aspp_out = F.interpolate(aspp_out, size=(x1.size(2), x1.size(3)), mode='bilinear', align_corners=self.align_corners)
        # feed to shortcut
        shortcut_out = self.shortcut(x1)
        # feed to decoder
        features = torch.cat([aspp_out, shortcut_out], dim=1)
        preds = self.decoder(features)
        # feed to auxiliary decoder and return according to the mode
        if self.mode == 'TRAIN':
            preds = F.interpolate(preds, size=(h, w), mode='bilinear', align_corners=self.align_corners)
            preds_aux = self.auxiliary_decoder(x3)
            preds_aux = F.interpolate(preds_aux, size=(h, w), mode='bilinear', align_corners=self.align_corners)
            return self.calculatelosses(
                predictions={'loss_cls': preds, 'loss_aux': preds_aux}, 
                targets=targets, 
                losses_cfg=losses_cfg
            )
        return preds
    '''return all layers'''
    def alllayers(self):
        return {
                'backbone_net': self.backbone_net, 
                'aspp_net': self.aspp_net, 
                'shortcut': self.shortcut,
                'decoder': self.decoder,
                'auxiliary_decoder': self.auxiliary_decoder
            }