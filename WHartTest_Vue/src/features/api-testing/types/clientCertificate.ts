import type { UserBrief } from './common';

/** 客户端证书形态：PEM（证书+私钥两文件） / PKCS#12（.pfx/.p12 单文件） */
export type ClientCertType = 'pem' | 'pkcs12';

/** 后端 serialize_file_for_runtime() 返回的文件摘要（用于列表展示） */
export interface ClientCertFileInfo {
  id: number;
  file_id: number;
  project_id: number;
  name: string;
  filename: string;
  size: number;
  sha256?: string;
  [key: string]: any;
}

export interface ApiClientCertificate {
  id: number;
  name: string;
  project: number;
  cert_type: ClientCertType;
  /** 证书文件 id（PEM=公钥证书，pkcs12=.pfx/.p12） */
  cert_file: number | null;
  cert_file_info: ClientCertFileInfo | null;
  /** 私钥文件 id（仅 PEM 需要） */
  key_file: number | null;
  key_file_info: ClientCertFileInfo | null;
  /** 只写：提交非空口令即设置；口令不会回显 */
  passphrase?: string;
  /** 只写：置 true 清除已保存口令 */
  clear_passphrase?: boolean;
  /** 只读：是否已保存口令 */
  has_passphrase: boolean;
  description: string;
  is_active: boolean;
  created_by: UserBrief | null;
  created_by_name?: string;
  created_at: string;
  updated_at: string;
  [key: string]: any;
}

export interface ClientCertValidationResult {
  valid: boolean;
  warnings: string[];
}
