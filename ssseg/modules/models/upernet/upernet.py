'''
Function:
    Implementation of UPerNet
Author:
    Zhenchao Jin
'''
import copy
import torch
import torch.nn as nn
import torch.nn.functional as F
from ...backbones import *
from ..base import BaseModel
from ..pspnet import PyramidPoolingModule


'''UPerNet'''
class UPerNet(BaseModel):
    def __init__(self, cfg, **kwargs):
        super(UPerNet, self).__init__(cfg, **kwargs)
        align_corners, normlayer_opts, activation_opts = self.align_corners, self.normlayer_opts, self.activation_opts
        # build pyramid pooling module
        ppm_cfg = {
            'in_channels': cfg['ppm']['in_channels'],
            'out_channels': cfg['ppm']['out_channels'],
            'bin_sizes': cfg['ppm']['bin_sizes'],
            'align_corners': align_corners,
            'normlayer_opts': copy.deepcopy(normlayer_opts),
            'activation_opts': copy.deepcopy(activation_opts),
        }
        self.ppm_net = PyramidPoolingModule(**ppm_cfg)
        # build lateral convs
        lateral_cfg = cfg['lateral']
        self.lateral_convs = nn.ModuleList()
        for in_channels in lateral_cfg['in_channels_list']:
            self.lateral_convs.append(
                nn.Sequential(
                    nn.Conv2d(in_channels, lateral_cfg['out_channels'], kernel_size=1, stride=1, padding=0, bias=False),
                    BuildNormalizationLayer(normlayer_opts['type'], (lateral_cfg['out_channels'], normlayer_opts['opts'])),
                    BuildActivation(activation_opts['type'], **activation_opts['opts']),
                )
            )
        # build decoder
        decoder_cfg = cfg['decoder']
        self.decoder = nn.Sequential(
            nn.Conv2d(decoder_cfg['in_channels'], decoder_cfg['out_channels'], kernel_size=3, stride=1, padding=1, bias=False),
            BuildNormalizationLayer(normlayer_opts['type'], (decoder_cfg['out_channels'], normlayer_opts['opts'])),
            BuildActivation(activation_opts['type'], **activation_opts['opts']),
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
        # feed to pyramid pooling module
        ppm_out = self.ppm_net(x4)
        # apply fpn
        lateral_outputs = [ppm_out]
        inputs = [x1, x2, x3]
        for idx in reversed(range(len(self.lateral_convs))):
            out = self.lateral_convs[idx](inputs[idx])
            out_prev = F.interpolate(lateral_outputs[-1], size=out.size()[2:], mode='bilinear', align_corners=self.align_corners)
            lateral_outputs.append(out + out_prev)
        fpn_out = [F.interpolate(out, size=x1.size()[2:], mode='bilinear', align_corners=self.align_corners) for out in lateral_outputs]
        fpn_out = torch.cat(fpn_out, dim=1)
        # feed to decoder
        preds = self.decoder(fpn_out)
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
                'ppm_net': self.ppm_net,
                'lateral_convs': self.lateral_convs,
                'decoder': self.decoder,
                'auxiliary_decoder': self.auxiliary_decoder
            }